"""Markdown-it configuration shared by the parser and renderer."""

from __future__ import annotations

from markdown_it import MarkdownIt
from markdown_it.rules_inline import StateInline


def _is_escaped(source: str, position: int) -> bool:
    """Return whether the character at *position* is backslash-escaped."""
    backslashes = 0
    position -= 1
    while position >= 0 and source[position] == "\\":
        backslashes += 1
        position -= 1
    return backslashes % 2 == 1


def _mark_rule(state: StateInline, silent: bool) -> bool:
    """Parse a non-nested ``==marked==`` span."""
    start = state.pos
    source = state.src
    if source[start : start + 2] != "==" or _is_escaped(source, start):
        return False
    if start + 2 >= len(source) or source[start + 2] == "=":
        return False

    end = start + 2
    while True:
        end = source.find("==", end)
        if end == -1:
            return False
        if not _is_escaped(source, end) and source[end + 2 : end + 3] != "=":
            break
        end += 2

    content = source[start + 2 : end]
    if not content or content.isspace():
        return False
    if silent:
        return True

    token = state.push("mark_open", "mark", 1)
    token.markup = "=="
    token = state.push("text", "", 0)
    token.content = content
    token = state.push("mark_close", "mark", -1)
    token.markup = "=="
    state.pos = end + 2
    return True


def mark_plugin(md: MarkdownIt) -> None:
    """Add the ``==marked==`` inline syntax used by cards.

    ``mdit-py-plugins`` does not expose its historical mark plugin in every
    supported release, so keep this small rule local.  Registering it in the
    inline ruler means code spans and dollar math consume their contents
    before this rule sees them.
    """
    md.inline.ruler.before("strikethrough", "mark", _mark_rule)


def markdown_it() -> MarkdownIt:
    """Return the configured Markdown-it instance used for card syntax."""
    from mdit_py_plugins.dollarmath import dollarmath_plugin

    return (
        MarkdownIt("commonmark", {"html": True}).use(mark_plugin).use(dollarmath_plugin)
    )
