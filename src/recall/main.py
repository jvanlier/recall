"""FastAPI web application for reviewing cards."""

from __future__ import annotations

import json
import mimetypes
import os
import secrets
import warnings as pywarnings
from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from recall.cards import Card, ParseResult
from recall.log import ReviewLog
from recall.parser import load_repo, markdown_files
from recall.render import RenderedCard, render_card
from recall.scheduler import Scheduler, load_config

_STATIC_DIR = Path(__file__).parent / "static"
_TEMPLATES_DIR = Path(__file__).parent / "templates"
_IMAGE_EXTENSIONS = {
    ".avif",
    ".bmp",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".png",
    ".svg",
    ".tif",
    ".tiff",
    ".webp",
}


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings for the web app."""

    cards_dir: Path
    host: str = "0.0.0.0"
    port: int = 8000

    def __post_init__(self) -> None:
        cards_dir = Path(self.cards_dir).expanduser()
        if not cards_dir.is_dir():
            raise ValueError(
                f"RECALL_CARDS_DIR must be an existing directory: {cards_dir}"
            )
        if not isinstance(self.host, str) or not self.host:
            raise ValueError("HOST must be a non-empty string")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("PORT must be an integer between 1 and 65535")
        object.__setattr__(self, "cards_dir", cards_dir)


AppSettings = Settings


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Read and validate settings from the environment."""
    values = os.environ if environ is None else environ
    cards_dir = values.get("RECALL_CARDS_DIR")
    if not cards_dir:
        raise ValueError("RECALL_CARDS_DIR is required and must point to a directory")

    raw_port = values.get("PORT", "8000")
    try:
        port = int(raw_port)
    except (TypeError, ValueError) as error:
        raise ValueError("PORT must be an integer between 1 and 65535") from error
    return Settings(
        cards_dir=Path(cards_dir),
        host=values.get("HOST", "0.0.0.0"),
        port=port,
    )


@dataclass(frozen=True, slots=True)
class AppWarning:
    """A warning displayed on the deck list."""

    text: str


@dataclass(slots=True)
class ReviewSession:
    """The small amount of per-browser state needed by the review loop."""

    scope: str
    reviewed: int = 0
    current_card: str | None = None
    presentation_token: str | None = None
    completed: bool = False


@dataclass(slots=True)
class DeckNode:
    """A folder or deck in the deck-list tree."""

    name: str
    path: str
    kind: str
    due: int
    new: int
    children: list[DeckNode] = field(default_factory=list)


@dataclass(slots=True)
class AppState:
    """Mutable application state shared by the routes."""

    settings: Settings
    log: ReviewLog
    parse_result: ParseResult | None = None
    scheduler: Scheduler | None = None
    markdown_fingerprint: tuple[tuple[str, int, int], ...] | None = None
    warnings: list[AppWarning] = field(default_factory=list)
    sessions: dict[str, ReviewSession] = field(default_factory=dict)


def _markdown_fingerprint(root: Path) -> tuple[tuple[str, int, int], ...]:
    result: list[tuple[str, int, int]] = []
    for path in markdown_files(root):
        stat = path.stat()
        result.append(
            (path.relative_to(root).as_posix(), stat.st_mtime_ns, stat.st_size)
        )
    return tuple(result)


def _warning_texts(
    parse_result: ParseResult, captured: list[object]
) -> list[AppWarning]:
    result = [
        AppWarning(f"{warning.file}:{warning.line}: {warning.message}")
        for warning in parse_result.warnings
    ]
    result.extend(AppWarning(f"review log: {warning}") for warning in captured)
    return result


def refresh_decks(state: AppState, *, force: bool = False) -> bool:
    """Reload decks and review state when a markdown file has changed."""
    fingerprint = _markdown_fingerprint(state.settings.cards_dir)
    if not force and state.scheduler is not None:
        if fingerprint == state.markdown_fingerprint:
            return False

    with pywarnings.catch_warnings(record=True) as captured:
        pywarnings.simplefilter("always")
        parse_result = load_repo(state.settings.cards_dir)
        reviews = state.log.read()
        config = load_config(state.settings.cards_dir)
        scheduler = Scheduler(parse_result, reviews, log=state.log, config=config)

    state.parse_result = parse_result
    state.scheduler = scheduler
    state.markdown_fingerprint = fingerprint
    state.warnings = _warning_texts(parse_result, list(captured))
    return True


def _normalise_scope(scope: str | None) -> str:
    if scope is None:
        return "all"
    value = scope.strip().strip("/")
    if not value or value in {".", "all", "*"}:
        return "all"
    if any(part in {".", ".."} for part in PurePosixPath(value).parts):
        return ""
    return value


def _known_scopes(parse_result: ParseResult) -> set[str]:
    scopes = {"all"}
    for deck in parse_result.decks:
        parts = deck.split("/")
        scopes.update("/".join(parts[:index]) for index in range(1, len(parts) + 1))
    return scopes


def _validated_scope(state: AppState, scope: str | None) -> str:
    value = _normalise_scope(scope)
    if (
        not value
        or state.parse_result is None
        or value not in _known_scopes(state.parse_result)
    ):
        raise HTTPException(status_code=400, detail="unknown review scope")
    return value


def _in_scope(card: Card, scope: str) -> bool:
    return scope == "all" or card.deck == scope or card.deck.startswith(f"{scope}/")


def _card_by_id(state: AppState, card_id: str) -> Card | None:
    if state.parse_result is None:
        return None
    return next((card for card in state.parse_result.cards if card.id == card_id), None)


def _session_from_cookie(
    request: Request, state: AppState, scope: str, *, replace: bool
) -> tuple[str, ReviewSession, bool]:
    token = request.cookies.get("recall_session")
    session = state.sessions.get(token) if token else None
    if session is None or replace:
        token = secrets.token_urlsafe(24)
        session = ReviewSession(scope=scope)
        state.sessions[token] = session
        return token, session, True
    if session.scope != scope:
        raise HTTPException(
            status_code=400, detail="review scope does not match session"
        )
    assert token is not None
    return token, session, False


def _present(session: ReviewSession, card: Card | None) -> None:
    """Record exactly which card presentation the browser is allowed to rate."""
    session.current_card = card.id if card is not None else None
    session.presentation_token = secrets.token_urlsafe(16) if card is not None else None
    session.completed = card is None


def _set_session_cookie(response, token: str, new: bool) -> None:
    if new:
        response.set_cookie(
            "recall_session",
            token,
            httponly=True,
            max_age=60 * 60 * 24 * 30,
            samesite="lax",
        )


def _tree_nodes(
    scheduler: Scheduler, parse_result: ParseResult, now: datetime
) -> list[DeckNode]:
    roots: list[DeckNode] = []
    by_path: dict[str, DeckNode] = {}
    for deck in parse_result.decks:
        parts = deck.split("/")
        parent_children = roots
        for index, name in enumerate(parts):
            path = "/".join(parts[: index + 1])
            node = by_path.get(path)
            if node is None:
                kind = "deck" if index == len(parts) - 1 else "folder"
                due, new = scheduler.counts(path, now)
                node = DeckNode(name, path, kind, due, new)
                by_path[path] = node
                parent_children.append(node)
                parent_children.sort(
                    key=lambda item: (item.kind != "folder", item.name.casefold())
                )
            parent_children = node.children
    return roots


def _rendered_card(state: AppState, card: Card) -> RenderedCard:
    return render_card(card, state.settings.cards_dir)


def _fragment_context(
    state: AppState, session: ReviewSession, card: Card | None
) -> dict[str, object]:
    if card is None:
        return {
            "card": None,
            "rendered": None,
            "session": session,
            "presentation_token": None,
            "pending": state.log.pending > 0,
        }
    return {
        "card": card,
        "rendered": _rendered_card(state, card),
        "session": session,
        "presentation_token": session.presentation_token,
        "pending": state.log.pending > 0,
    }


async def _request_payload(request: Request) -> dict[str, object]:
    body = await request.body()
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise HTTPException(status_code=400, detail="invalid JSON body") from error
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=400, detail="request body must be an object"
            )
        for key, value in request.query_params.multi_items():
            payload.setdefault(key, value)
        return payload
    try:
        values = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    except UnicodeDecodeError as error:
        raise HTTPException(
            status_code=400, detail="request body is not UTF-8"
        ) from error
    payload: dict[str, object] = {
        key: items[-1] for key, items in values.items() if items
    }
    for key, value in request.query_params.multi_items():
        payload.setdefault(key, value)
    return payload


def _required_string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise HTTPException(status_code=400, detail=f"{key} is required")
    return value


def _required_integer(
    payload: Mapping[str, object], key: str, *, minimum: int, maximum: int | None = None
) -> int:
    value = payload.get(key)
    if isinstance(value, bool):
        raise HTTPException(status_code=400, detail=f"{key} must be an integer")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and value.isdecimal():
        result = int(value)
    else:
        raise HTTPException(status_code=400, detail=f"{key} must be an integer")
    if result < minimum or (maximum is not None and result > maximum):
        limit = f" through {maximum}" if maximum is not None else " or greater"
        raise HTTPException(status_code=400, detail=f"{key} must be {minimum}{limit}")
    return result


def _review_response(
    request: Request,
    templates: Jinja2Templates,
    state: AppState,
    session: ReviewSession,
    card: Card | None,
    *,
    full_page: bool = False,
):
    context = _fragment_context(state, session, card)
    if full_page:
        response = templates.TemplateResponse(
            request=request,
            name="review.html",
            context=context,
        )
    else:
        response = templates.TemplateResponse(
            request=request,
            name="review_card.html",
            context=context,
        )
    return response


def _media_file(root: Path, raw_path: str) -> Path:
    """Validate a media URL and return its in-repository file."""
    if not raw_path or "\x00" in raw_path or "\\" in raw_path:
        raise HTTPException(status_code=404, detail="media file not found")
    path = PurePosixPath(raw_path)
    if (
        path.is_absolute()
        or ".." in path.parts
        or any(part.startswith(".") for part in path.parts[:-1])
    ):
        raise HTTPException(status_code=404, detail="media file not found")
    if Path(path.name).suffix.lower() not in _IMAGE_EXTENSIONS:
        raise HTTPException(status_code=404, detail="media file not found")

    candidate = (root / Path(*path.parts)).resolve()
    try:
        relative = candidate.relative_to(root.resolve())
    except ValueError as error:
        raise HTTPException(status_code=404, detail="media file not found") from error
    if (
        any(part.startswith(".") for part in relative.parts[:-1])
        or not candidate.is_file()
        or candidate.suffix.lower() not in _IMAGE_EXTENSIONS
    ):
        raise HTTPException(status_code=404, detail="media file not found")
    return candidate


def create_app(settings: Settings | Mapping[str, object] | None = None) -> FastAPI:
    """Create the review web application."""
    if settings is None:
        app_settings = load_settings()
    elif isinstance(settings, Settings):
        app_settings = settings
    else:
        raw_cards_dir = settings.get("cards_dir", settings.get("RECALL_CARDS_DIR"))
        if not isinstance(raw_cards_dir, (str, Path)):
            raise ValueError(
                "RECALL_CARDS_DIR is required and must point to a directory"
            )
        raw_host = settings.get("host", settings.get("HOST", "0.0.0.0"))
        raw_port = settings.get("port", settings.get("PORT", 8000))
        if not isinstance(raw_host, str):
            raise ValueError("HOST must be a non-empty string")
        if not isinstance(raw_port, (str, int)) or isinstance(raw_port, bool):
            raise ValueError("PORT must be an integer between 1 and 65535")
        try:
            port = int(raw_port)
        except ValueError as error:
            raise ValueError("PORT must be an integer between 1 and 65535") from error
        app_settings = Settings(
            cards_dir=Path(raw_cards_dir),
            host=raw_host,
            port=port,
        )

    state = AppState(
        settings=app_settings,
        log=ReviewLog(app_settings.cards_dir / ".recall" / "reviews.jsonl"),
    )
    templates = Jinja2Templates(directory=_TEMPLATES_DIR)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        refresh_decks(state, force=True)
        yield

    app = FastAPI(title="recall", lifespan=lifespan)
    app.state.recall = state
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    @app.get("/healthz", name="healthz")
    async def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @app.get("/manifest.webmanifest", name="manifest")
    async def manifest() -> FileResponse:
        return FileResponse(
            _STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json"
        )

    @app.get("/", name="deck_list")
    async def deck_list(request: Request) -> HTMLResponse:
        refresh_decks(state)
        assert state.parse_result is not None and state.scheduler is not None
        now = datetime.now(UTC)
        return templates.TemplateResponse(
            request=request,
            name="deck_list.html",
            context={
                "tree": _tree_nodes(state.scheduler, state.parse_result, now),
                "warnings": state.warnings,
            },
        )

    async def show_review(request: Request, scope: str | None) -> HTMLResponse:
        refresh_decks(state)
        assert state.scheduler is not None
        value = _validated_scope(state, scope)
        token, session, new = _session_from_cookie(request, state, value, replace=True)
        card = state.scheduler.next_card(value, datetime.now(UTC))
        _present(session, card)
        response = _review_response(
            request, templates, state, session, card, full_page=True
        )
        _set_session_cookie(response, token, new)
        return response

    @app.get("/review", name="review")
    async def review(request: Request, scope: str | None = None) -> HTMLResponse:
        return await show_review(request, scope)

    @app.get("/review/{scope:path}", name="review_path")
    async def review_path(request: Request, scope: str) -> HTMLResponse:
        return await show_review(request, scope)

    @app.post("/review/rate", name="rate")
    async def rate(request: Request):
        refresh_decks(state)
        assert state.scheduler is not None
        payload = await _request_payload(request)
        card_key = "card" if "card" in payload else "card_id"
        elapsed_key = "ms" if "ms" in payload else "elapsed_ms"
        card_id = _required_string(payload, card_key)
        submitted_scope = _validated_scope(state, _required_string(payload, "scope"))
        rating = _required_integer(payload, "rating", minimum=1, maximum=4)
        elapsed = _required_integer(payload, elapsed_key, minimum=0)
        token, session, new = _session_from_cookie(
            request, state, submitted_scope, replace=False
        )
        card = _card_by_id(state, card_id)
        if card is None or card.hidden or not _in_scope(card, submitted_scope):
            raise HTTPException(status_code=400, detail="unknown card ID for scope")
        presentation = _required_string(payload, "presentation")
        if (
            session.current_card != card_id
            or session.presentation_token != presentation
        ):
            raise HTTPException(status_code=400, detail="card is no longer presented")

        state.scheduler.record(card_id, rating, elapsed, datetime.now(UTC))
        session.reviewed += 1
        next_card = state.scheduler.next_card(submitted_scope, datetime.now(UTC))
        _present(session, next_card)
        response = _review_response(request, templates, state, session, next_card)
        _set_session_cookie(response, token, new)
        return response

    @app.post("/review/undo", name="undo")
    async def undo(request: Request):
        refresh_decks(state)
        assert state.scheduler is not None
        payload = await _request_payload(request)
        submitted_scope = _validated_scope(state, _required_string(payload, "scope"))
        token, session, new = _session_from_cookie(
            request, state, submitted_scope, replace=False
        )
        removed = state.scheduler.undo()
        if removed is not None:
            session.reviewed = max(0, session.reviewed - 1)
        card = _card_by_id(state, removed.card) if removed is not None else None
        if card is None or card.hidden or not _in_scope(card, submitted_scope):
            card = state.scheduler.next_card(submitted_scope, datetime.now(UTC))
        _present(session, card)
        response = _review_response(request, templates, state, session, card)
        _set_session_cookie(response, token, new)
        return response

    @app.post("/review/done", name="done")
    async def done(request: Request):
        refresh_decks(state)
        payload = await _request_payload(request)
        submitted_scope = _validated_scope(state, _required_string(payload, "scope"))
        token, session, new = _session_from_cookie(
            request, state, submitted_scope, replace=False
        )
        _present(session, None)
        response = _review_response(request, templates, state, session, None)
        _set_session_cookie(response, token, new)
        return response

    @app.get("/media/{path:path}", name="media")
    async def media(path: str):
        file_path = _media_file(app_settings.cards_dir, path)
        media_type = (
            mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        )
        headers = {"X-Content-Type-Options": "nosniff"}
        if file_path.suffix.lower() == ".svg":
            headers["Content-Security-Policy"] = "sandbox"
        return FileResponse(file_path, media_type=media_type, headers=headers)

    return app


__all__ = ["AppSettings", "Settings", "create_app", "load_settings", "refresh_decks"]
