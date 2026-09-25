"""Render parsed cards as safe HTML for the web UI."""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from html import escape
from pathlib import Path, PurePosixPath
from types import MethodType
from typing import Literal, cast
from urllib.parse import quote, unquote, urlsplit

from markdown_it.renderer import RendererHTML
from markdown_it.token import Token
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
    if not path or "\x00" in path or "\\" in path:
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
    if not path or "\x00" in path or "\\" in path:
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


def _markdown_renderer(card: Card, cards_root: Path | None):
    md = markdown_it(html=False)
    md.enable(["table", "strikethrough"])
    md.options["highlight"] = _highlight_code
    renderer = cast(RendererHTML, md.renderer)
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

    replacements: list[tuple[str, str]] = []
    transformed: list[str] = []
    position = 0
    for index, span in enumerate(spans):
        deleted = source[span.start + 2 : span.end - 2]
        if index == selected:
            if answer:
                inner = md.renderInline(deleted)
                replacement = f'<mark class="cloze-answer">{inner}</mark>'
            else:
                hint = (
                    source[span.hint_start : span.hint_end - 1]
                    if span.hint_start is not None
                    else "…"
                )
                replacement = '<span class="cloze">[' + escape(hint) + "]</span>"
            placeholder = f"\ue000recall-cloze-{index}\ue001"
            while placeholder in source:
                placeholder += "x"
            replacements.append((placeholder, replacement))
            transformed.append(source[position : span.start])
            transformed.append(placeholder)
        else:
            transformed.append(source[position : span.start])
            transformed.append(deleted)
        position = span.hint_end
    transformed.append(source[position:])

    rendered = md.render("".join(transformed))
    for placeholder, replacement in replacements:
        rendered = rendered.replace(placeholder, replacement)
    return rendered


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
