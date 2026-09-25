"""Validate a cards repository for parser and filesystem problems."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from recall.cards import ParseResult, Warning
from recall.markdown import code_span_end, markdown_it, math_span_end
from recall.parser import load_repo, markdown_files

_MARKDOWN = markdown_it()
_IGNORED_TOKEN_TYPES = {
    "code_block",
    "fence",
    "math_block",
    "math_block_label",
}


def _is_escaped(source: str, position: int) -> bool:
    """Return whether the character at *position* is backslash-escaped."""
    backslashes = 0
    position -= 1
    while position >= 0 and source[position] == "\\":
        backslashes += 1
        position -= 1
    return backslashes % 2 == 1


def _warning(file: Path, line: int, message: str) -> Warning:
    return Warning(file=file, line=line, message=message)


def _ignored_mask(source: str, *, include_math: bool = False) -> list[bool]:
    """Mask comments and code, and optionally math, in *source*."""
    mask = [False] * len(source)
    position = 0
    while position < len(source):
        if source.startswith("<!--", position):
            close = source.find("-->", position + 4)
            end = len(source) if close == -1 else close + 3
            mask[position:end] = [True] * (end - position)
            position = end
            continue
        if source[position] == "`":
            end = code_span_end(source, position)
            if end is not None:
                mask[position:end] = [True] * (end - position)
                position = end
                continue
        if include_math and source[position] == "$" and not _is_escaped(source, position):
            end = math_span_end(source, position)
            if end is not None:
                mask[position:end] = [True] * (end - position)
                position = end
                continue
        position += 1
    return mask


def _image_marker_positions(source: str, env: dict[str, Any]) -> list[int]:
    """Find image markers that markdown-it recognizes in *source*."""
    ignored = _ignored_mask(source, include_math=True)
    positions: list[int] = []
    position = 0
    while True:
        position = source.find("![", position)
        if position == -1:
            return positions
        if not ignored[position] and not _is_escaped(source, position):
            parsed = _MARKDOWN.parseInline(source[position:], env)
            children = parsed[0].children if parsed else None
            if children and children[0].type == "image":
                positions.append(position)
        position += 2


def _image_warnings(root: Path, path: Path) -> list[Warning]:
    source = path.read_text(encoding="utf-8")
    relative_file = path.relative_to(root)
    warnings: list[Warning] = []
    env: dict[str, Any] = {}

    for token in _MARKDOWN.parse(source, env):
        if token.type != "inline" or token.children is None:
            continue
        first_line = 1 if token.map is None else token.map[0] + 1
        marker_positions = _image_marker_positions(token.content, env)
        marker_index = 0
        for child in token.children:
            if child.type != "image" or child.attrs is None:
                continue
            src = child.attrs.get("src")
            if not isinstance(src, str):
                continue

            position = marker_positions[marker_index] if marker_index < len(marker_positions) else -1
            marker_index += 1
            line = first_line + token.content.count("\n", 0, position) if position != -1 else first_line
            warnings.extend(
                _check_image_path(
                    root,
                    path,
                    relative_file,
                    line,
                    src,
                )
            )
    return warnings


def _check_image_path(
    root: Path,
    markdown_file: Path,
    relative_file: Path,
    line: int,
    src: str,
) -> list[Warning]:
    try:
        parsed = urlsplit(src)
    except ValueError:
        return [_warning(relative_file, line, f"invalid image path: {src!r}")]

    if parsed.scheme or parsed.netloc:
        return [
            _warning(
                relative_file,
                line,
                f"image path must be relative: {src!r}",
            )
        ]

    image_name = unquote(parsed.path)
    image_path = Path(image_name)
    if image_path.is_absolute():
        return [
            _warning(
                relative_file,
                line,
                f"image path escapes repository: {src!r}",
            )
        ]

    try:
        resolved = (markdown_file.parent / image_path).resolve(strict=False)
    except OSError, RuntimeError, ValueError:
        return [_warning(relative_file, line, f"invalid image path: {src!r}")]

    if not resolved.is_relative_to(root):
        return [
            _warning(
                relative_file,
                line,
                f"image path escapes repository: {src!r}",
            )
        ]
    if not resolved.is_file():
        return [_warning(relative_file, line, f"missing image: {src!r}")]
    return []


def _closing_delimiter(source: str, start: int, delimiter: str) -> int | None:
    """Find a math close delimiter, including inside code or comments."""
    position = start
    while position < len(source):
        if source.startswith(delimiter, position) and not _is_escaped(source, position):
            return position
        position += 1
    return None


def _math_warnings_in_text(file: Path, source: str, first_line: int) -> list[Warning]:
    warnings: list[Warning] = []
    position = 0
    while position < len(source):
        if source.startswith("<!--", position):
            close = source.find("-->", position + 4)
            position = len(source) if close == -1 else close + 3
            continue
        if source[position] == "`":
            end = code_span_end(source, position)
            if end is not None:
                position = end
                continue
        if source[position] != "$" or _is_escaped(source, position):
            position += 1
            continue

        delimiter = "$$" if source.startswith("$$", position) else "$"
        close = _closing_delimiter(source, position + len(delimiter), delimiter)
        if close is None:
            warnings.append(
                _warning(
                    file,
                    first_line + source.count("\n", 0, position),
                    f"unclosed math delimiter {delimiter!r}",
                )
            )
            break
        position = close + len(delimiter)
    return warnings


def _math_warnings(root: Path, path: Path) -> list[Warning]:
    source = path.read_text(encoding="utf-8")
    relative_file = path.relative_to(root)
    warnings: list[Warning] = []
    for token in _MARKDOWN.parse(source):
        if token.type in _IGNORED_TOKEN_TYPES:
            continue
        if token.type != "inline" or token.map is None:
            continue
        warnings.extend(
            _math_warnings_in_text(
                relative_file,
                token.content,
                token.map[0] + 1,
            )
        )
    return warnings


def check_repo(root: Path) -> ParseResult:
    """Parse and validate *root*, returning all cards and problems."""
    root = Path(root).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"cards repository is not a directory: {root}")

    result = load_repo(root)
    problems = list(result.warnings)
    for path in markdown_files(root):
        problems.extend(_image_warnings(root, path))
        problems.extend(_math_warnings(root, path))

    result.warnings[:] = sorted(
        problems,
        key=lambda warning: (warning.file.as_posix(), warning.line, warning.message),
    )
    return result
