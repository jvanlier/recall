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


def code_span_end(source: str, start: int) -> int | None:
    """Return the end of a CommonMark code span, if *start* opens one."""
    if source[start] != "`" or _is_escaped(source, start):
        return None
    run_end = start
    while run_end < len(source) and source[run_end] == "`":
        run_end += 1
    delimiter = source[start:run_end]
    close = source.find(delimiter, run_end)
    if close == -1 or "\n\n" in source[run_end:close]:
        return None
    return close + len(delimiter)


def math_span_end(source: str, start: int) -> int | None:
    """Return the end of an inline dollar-math span, if present."""
    if source[start] != "$" or _is_escaped(source, start):
        return None
    delimiter = "$$" if source.startswith("$$", start) else "$"
    close = source.find(delimiter, start + len(delimiter))
    while close != -1 and _is_escaped(source, close):
        close = source.find(delimiter, close + len(delimiter))
    return None if close == -1 else close + len(delimiter)


def _mark_rule(state: StateInline, silent: bool) -> bool:
    """Parse a non-nested ``==marked==`` span."""
    start = state.pos
    source = state.src
    if source[start : start + 2] != "==" or _is_escaped(source, start):
        return False
    if start + 2 >= len(source) or source[start + 2] == "=":
        return False

    end = start + 2
    while end < len(source):
        if source.startswith("==", end) and not _is_escaped(source, end):
            if source[end + 2 : end + 3] != "=":
                break
            end += 2
            continue
        if source[end] == "`":
            protected_end = code_span_end(source, end)
            if protected_end is not None:
                end = protected_end
                continue
        if source[end] == "$":
            protected_end = math_span_end(source, end)
            if protected_end is not None:
                end = protected_end
                continue
        end += 1
    else:
        return False

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
