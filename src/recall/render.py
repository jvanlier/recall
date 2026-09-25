"""Render parsed cards as safe HTML for the web UI."""

from __future__ import annotations

import posixpath
from collections.abc import Sequence
from dataclasses import dataclass
from html import escape
from pathlib import Path, PurePosixPath
from types import MethodType
from typing import Literal, cast
from urllib.parse import quote, unquote, urlsplit

from markdown_it.renderer import RendererHTML
from markdown_it.token import Token
from markdown_it.utils import EnvType, OptionsDict
from pygments import highlight
from pygments.formatters.html import HtmlFormatter
from pygments.lexers import ClassNotFound, get_lexer_by_name

from recall.cards import Card
from recall.markdown import markdown_it
from recall.parser import find_cloze_spans


@dataclass(frozen=True, slots=True)
class RenderedCard:
    """The question and answer HTML for one card."""

    front_html: str
    back_html: str


_PYGMENTS_STYLES = {"light": "default", "dark": "monokai"}
_CLOZE_MARKER_START = "[[recall-cloze-"
_CLOZE_MARKER_END = "]]"
_CLOZE_ENV = "recall_cloze_replacements"


def pygments_css(theme: Literal["light", "dark"] = "light") -> str:
    """Generate the Pygments CSS for a light or dark code theme."""
    try:
        style = _PYGMENTS_STYLES[theme]
    except KeyError as error:
        raise ValueError("theme must be 'light' or 'dark'") from error
    return HtmlFormatter(style=style).get_style_defs("pre code")


def _highlight_code(code: str, language: str, _attrs: str) -> str:
    if not language:
        return ""
    try:
        lexer = get_lexer_by_name(language)
    except ClassNotFound:
        return ""
    return highlight(code, lexer, HtmlFormatter(nowrap=True))


def _normalise_media_path(card_file: Path, source: str) -> str | None:
    """Resolve a relative image source without leaving the visible repo tree."""
    parsed = urlsplit(source)
    if parsed.scheme or parsed.netloc or parsed.path.startswith("/"):
        return None

    path = unquote(parsed.path)
    if not path or path.startswith("/") or "\x00" in path or "\\" in path:
        return None

    normalised = posixpath.normpath(posixpath.join(card_file.parent.as_posix(), path))
    if normalised in {"", ".", ".."} or normalised.startswith("../"):
        return None

    relative = PurePosixPath(normalised)
    if any(part.startswith(".") for part in relative.parts[:-1]):
        return None
    return relative.as_posix()


def _media_url(card_file: Path, source: str, cards_root: Path | None) -> str | None:
    """Return a URL-encoded media URL, checking symlinks when a root is given."""
    parsed = urlsplit(source)
    if parsed.scheme or parsed.netloc or parsed.path.startswith("/"):
        return None
    path = unquote(parsed.path)
    if not path or path.startswith("/") or "\x00" in path or "\\" in path:
        return None

    if cards_root is None:
        relative = _normalise_media_path(card_file, source)
    else:
        root = cards_root.resolve()
        source_file = card_file if card_file.is_absolute() else root / card_file
        candidate = (source_file.parent / path).resolve()
        try:
            relative_path = candidate.relative_to(root)
        except ValueError:
            return None
        relative = relative_path.as_posix()
        if any(part.startswith(".") for part in relative_path.parts[:-1]):
            return None

    if relative is None:
        return None
    return "/media/" + quote(relative, safe="/")


def _invalid_image(tokens: list[Token], index: int) -> str:
    alt = tokens[index].content
    label = "invalid image" if not alt else f"invalid image: {alt}"
    return f'<span class="invalid-image" role="img">{escape(label)}</span>'


def _cloze_from_env(env, marker: str):
    replacements = env.get(_CLOZE_ENV, {}) if isinstance(env, dict) else {}
    return replacements.get(marker) if isinstance(replacements, dict) else None


class _RecallRenderer(RendererHTML):
    def renderInlineAsText(
        self,
        tokens: Sequence[Token] | None,
        options: OptionsDict,
        env: EnvType,
    ) -> str:
        result: list[str] = []
        for token in tokens or []:
            if token.type == "recall_cloze":
                replacement = _cloze_from_env(env, token.content)
                result.append(
                    replacement[1] if replacement is not None else token.content
                )
            else:
                result.append(super().renderInlineAsText([token], options, env))
        return "".join(result)


def _markdown_renderer(card: Card, cards_root: Path | None):
    md = markdown_it(html=False, renderer_cls=_RecallRenderer)
    md.enable(["table", "strikethrough"])
    md.options["highlight"] = _highlight_code
    renderer = cast(RendererHTML, md.renderer)

    def parse_cloze_marker(state, silent):
        start = state.pos
        if not state.src.startswith(_CLOZE_MARKER_START, start):
            return False
        marker_end = state.src.find(_CLOZE_MARKER_END, start + len(_CLOZE_MARKER_START))
        if marker_end == -1:
            return False
        marker_end += len(_CLOZE_MARKER_END)
        if not silent:
            token = state.push("recall_cloze", "", 0)
            token.content = state.src[start:marker_end]
        state.pos = marker_end
        return True

    md.inline.ruler.before("text", "recall_cloze", parse_cloze_marker)

    def render_cloze(tokens, index, _options, env):
        replacement = _cloze_from_env(env, tokens[index].content)
        return (
            replacement[0] if replacement is not None else escape(tokens[index].content)
        )

    renderer.rules["recall_cloze"] = cast(MethodType, render_cloze)

    default_image = renderer.rules["image"]

    def render_image(tokens, index, options, env):
        token = tokens[index]
        source = token.attrGet("src") or ""
        media_url = _media_url(card.file, source, cards_root)
        if media_url is None:
            return _invalid_image(tokens, index)
        token.attrSet("src", media_url)
        return default_image(tokens, index, options, env)

    renderer.rules["image"] = cast(MethodType, render_image)
    return md


def _cloze_replacement(
    source: str,
    selected: int,
    md,
    *,
    answer: bool,
) -> str:
    spans = find_cloze_spans(source)
    if not 0 <= selected < len(spans):
        raise ValueError("cloze card has an invalid deletion index")

    replacements: dict[str, tuple[str, str]] = {}
    transformed: list[str] = []
    selected_deleted = ""
    selected_placeholder = ""
    position = 0
    for index, span in enumerate(spans):
        deleted = source[span.start + 2 : span.end - 2]
        if index == selected:
            selected_deleted = deleted
            hint = (
                source[span.hint_start : span.hint_end - 1]
                if span.hint_start is not None
                else "…"
            )
            selected_placeholder = f"{_CLOZE_MARKER_START}{index}{_CLOZE_MARKER_END}"
            collision = 0
            while selected_placeholder in source:
                collision += 1
                selected_placeholder = (
                    f"{_CLOZE_MARKER_START}{index}-{'x' * collision}{_CLOZE_MARKER_END}"
                )
            fallback = f"[{hint}]"
            replacements[selected_placeholder] = ("", fallback)
            transformed.append(source[position : span.start])
            transformed.append(selected_placeholder)
        else:
            transformed.append(source[position : span.start])
            transformed.append(deleted)
        position = span.hint_end
    transformed.append(source[position:])

    environment: dict[str, object] = {_CLOZE_ENV: replacements}
    tokens = md.parse("".join(transformed), environment)
    if answer:
        inner = md.renderInline(selected_deleted, environment)
        replacement = f'<mark class="cloze-answer">{inner}</mark>'
        alt = selected_deleted
    else:
        replacement = (
            '<span class="cloze">'
            + escape(replacements[selected_placeholder][1])
            + "</span>"
        )
        alt = replacements[selected_placeholder][1]
    replacements[selected_placeholder] = (replacement, alt)
    return md.renderer.render(tokens, md.options, environment)


def _render_cloze(card: Card, md, *, answer: bool) -> str:
    source = card.cloze_text or card.front
    if card.cloze_index is None:
        raise ValueError("cloze card has no deletion index")
    return _cloze_replacement(source, card.cloze_index, md, answer=answer)


def render_card(card: Card, cards_root: Path | None = None) -> RenderedCard:
    """Render *card* into question and answer HTML.

    ``cards_root`` is optional because parsed cards carry repository-relative
    paths.  Supplying it additionally verifies symlinks before creating media
    URLs, matching the serving layer's defence-in-depth check.
    """
    md = _markdown_renderer(card, cards_root)
    if card.kind == "cloze":
        return RenderedCard(
            front_html=_render_cloze(card, md, answer=False),
            back_html=_render_cloze(card, md, answer=True),
        )

    front_html = md.render(card.front)
    back_html = md.render(card.back)
    return RenderedCard(
        front_html=front_html,
        back_html=front_html + "<hr>\n" + back_html,
    )
