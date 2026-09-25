"""Tests for the FastAPI review application."""

import asyncio
import json
import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from recall.gitsync import GitSync, SyncResult
from recall.log import ReviewLog
from recall.main import AppState, Settings, _run_sync, create_app
from recall.parser import load_repo


def app_for(tmp_path: Path, source: str = "Question::Answer\n"):
    (tmp_path / "Deck.md").write_text(source, encoding="utf-8")
    return create_app(Settings(tmp_path))


def presentation_token(html: str) -> str:
    match = re.search(r'name="presentation" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def test_deck_list_counts_and_healthz(tmp_path: Path) -> None:
    with TestClient(app_for(tmp_path)) as client:
        assert client.get("/healthz").status_code == 200
        response = client.get("/")

    assert response.status_code == 200
    assert "Deck" in response.text
    assert ">0</strong> due" in response.text
    assert ">1</strong> new" in response.text


def test_browse_renders_fixture_cards_including_hidden_cards() -> None:
    cards_dir = Path(__file__).parents[1] / "examples" / "cards"
    with TestClient(create_app(Settings(cards_dir, git_sync=False))) as client:
        response = client.get("/browse/Foundations")

    assert response.status_code == 200
    assert response.text.count('<article class="browse-card') == 9
    assert "This card is hidden from the review queue." in response.text
    assert "card-status-hidden" in response.text
    assert '<span class="math inline">x^2</span>' in response.text
    assert 'src="/media/images/recall.svg"' in response.text
    assert "Foundations.md" in response.text


def test_browse_links_are_available_for_decks_and_folders(tmp_path: Path) -> None:
    (tmp_path / "Folder").mkdir()
    (tmp_path / "Folder" / "Deck.md").write_text("Question::Answer\n", encoding="utf-8")

    with TestClient(create_app(Settings(tmp_path, git_sync=False))) as client:
        response = client.get("/")
        folder = client.get("/browse/Folder")

    assert 'href="/browse/Folder"' in response.text
    assert folder.status_code == 200
    assert "Question" in folder.text


def test_manifest_is_served_as_installable_web_manifest(tmp_path: Path) -> None:
    with TestClient(create_app(Settings(tmp_path, git_sync=False))) as client:
        response = client.get("/manifest.webmanifest")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/manifest+json")
    manifest = json.loads(response.text)
    assert manifest["display"] == "standalone"
    assert {icon["sizes"] for icon in manifest["icons"]} >= {"192x192", "512x512"}


def test_timed_out_sync_refreshes_when_worker_finishes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "Deck.md").write_text("Question::Answer\n", encoding="utf-8")
    settings = Settings(tmp_path, git_sync_timeout=0.01)
    log = ReviewLog(tmp_path / ".recall" / "reviews.jsonl")
    syncer = GitSync(tmp_path, log)
    state = AppState(settings=settings, log=log, git_sync=syncer)

    def slow_sync() -> SyncResult:
        time.sleep(0.05)
        return SyncResult(head_changed=True)

    monkeypatch.setattr(syncer, "sync", slow_sync)

    async def exercise() -> None:
        result = await _run_sync(state, force=True)
        assert result is not None and result.error is not None
        await asyncio.sleep(0.1)

    asyncio.run(exercise())

    assert state.sync_error is None
    assert state.scheduler is not None


def test_final_rating_triggers_sync(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".recall").mkdir()
    (tmp_path / ".recall" / "config.toml").write_text("learn_ahead_minutes = 0\n", encoding="utf-8")
    app = app_for(tmp_path)
    card = load_repo(tmp_path).cards[0]
    calls: list[bool] = []

    def sync() -> SyncResult:
        calls.append(True)
        return SyncResult()

    with TestClient(app) as client:
        syncer = app.state.recall.git_sync
        assert syncer is not None
        monkeypatch.setattr(syncer, "sync", sync)
        response = client.get("/review/Deck")
        response = client.post(
            "/review/rate",
            data={
                "card": card.id,
                "scope": "Deck",
                "rating": "3",
                "ms": "42",
                "presentation": presentation_token(response.text),
            },
        )
        assert "Session complete" in response.text
        assert calls


def test_review_cycle_appends_to_log(tmp_path: Path) -> None:
    app = app_for(tmp_path)
    card = load_repo(tmp_path).cards[0]

    with TestClient(app) as client:
        response = client.get("/review/Deck")
        assert response.status_code == 200
        assert "Question" in response.text
        response = client.post(
            "/review/rate",
            data={
                "card": card.id,
                "scope": "Deck",
                "rating": "3",
                "ms": "42",
                "presentation": presentation_token(response.text),
            },
        )
        assert response.status_code == 200
        assert 'data-reviewed="1"' in response.text
        response = client.post("/review/done", data={"scope": "Deck"})
        assert "Session complete" in response.text
        assert "Undo last rating" in response.text

    assert '"rating": 3' in (tmp_path / ".recall" / "reviews.jsonl").read_text(encoding="utf-8")


def test_stale_rating_is_rejected_and_new_session_resets_count(tmp_path: Path) -> None:
    app = app_for(tmp_path)
    card = load_repo(tmp_path).cards[0]

    with TestClient(app) as client:
        response = client.get("/review/Deck")
        payload = {
            "card": card.id,
            "scope": "Deck",
            "rating": "3",
            "ms": "42",
            "presentation": presentation_token(response.text),
        }
        assert client.post("/review/rate", data=payload).status_code == 200
        assert client.post("/review/rate", data=payload).status_code == 400
        response = client.get("/review/Deck")

    assert "0 reviewed" in response.text


def test_undo_removes_last_review_and_shows_card_again(tmp_path: Path) -> None:
    app = app_for(tmp_path)
    card = load_repo(tmp_path).cards[0]

    with TestClient(app) as client:
        response = client.get("/review/Deck")
        client.post(
            "/review/rate",
            data={
                "card": card.id,
                "scope": "Deck",
                "rating": "3",
                "ms": "42",
                "presentation": presentation_token(response.text),
            },
        )
        response = client.post("/review/undo", data={"scope": "Deck"})

    assert response.status_code == 200
    assert "Question" in response.text
    assert not (tmp_path / ".recall" / "reviews.jsonl").read_text(encoding="utf-8")


def test_deck_links_encode_url_delimiters(tmp_path: Path) -> None:
    (tmp_path / "C#.md").write_text("Question one::Answer one\n", encoding="utf-8")
    (tmp_path / "Folder?Name.md").write_text("Question two::Answer two\n", encoding="utf-8")

    with TestClient(create_app(Settings(tmp_path))) as client:
        response = client.get("/")
        assert 'href="/review/C%23"' in response.text
        assert 'href="/review/Folder%3FName"' in response.text
        assert client.get("/review/C%23").status_code == 200
        assert client.get("/review/Folder%3FName").status_code == 200


def test_invalid_card_and_rating_are_rejected(tmp_path: Path) -> None:
    with TestClient(app_for(tmp_path)) as client:
        assert (
            client.post(
                "/review/rate",
                data={"card": "missing", "scope": "Deck", "rating": "3", "ms": "0"},
            ).status_code
            == 400
        )
        card = load_repo(tmp_path).cards[0]
        assert (
            client.post(
                "/review/rate",
                data={"card": card.id, "scope": "Deck", "rating": "5", "ms": "0"},
            ).status_code
            == 400
        )


def test_media_validation(tmp_path: Path) -> None:
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "present.png").write_bytes(b"png")
    (tmp_path / "notes.txt").write_text("not media", encoding="utf-8")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "secret.png").write_bytes(b"secret")
    outside = tmp_path.parent / "recall-media-outside.png"
    outside.write_bytes(b"outside")
    payload = tmp_path / "payload.html"
    payload.write_text("<script>alert(1)</script>", encoding="utf-8")
    (tmp_path / "escape.png").symlink_to(outside)
    (tmp_path / "active.png").symlink_to(payload)
    (tmp_path / "active.svg").write_text("<svg><script>alert(1)</script></svg>", encoding="utf-8")

    try:
        with TestClient(app_for(tmp_path)) as client:
            assert client.get("/media/images/present.png").status_code == 200
            assert client.get("/media/notes.txt").status_code == 404
            assert client.get("/media/.hidden/secret.png").status_code == 404
            assert client.get("/media/escape.png").status_code == 404
            assert client.get("/media/active.png").status_code == 404
            svg = client.get("/media/active.svg")
            assert svg.status_code == 200
            assert svg.headers["content-security-policy"] == "sandbox"
            assert svg.headers["x-content-type-options"] == "nosniff"
    finally:
        outside.unlink()
