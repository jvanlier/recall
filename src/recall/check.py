"""Validate a cards repository for parser and filesystem problems."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlsplit

from markdown_it.token import Token

from recall.cards import ParseResult, Warning
from recall.markdown import code_span_end, markdown_it
from recall.parser import load_repo, markdown_files

_MARKDOWN = markdown_it()
_IGNORED_TOKEN_TYPES = {
    "code_block",
    "fence",
    "math_block",
    "math_block_label",
}


def _warning(file: Path, line: int, message: str) -> Warning:
    return Warning(file=file, line=line, message=message)


def _image_position(source: str, start: int) -> tuple[int, int]:
    """Find the next image source marker and its syntax length."""
    marker = source.find("![", start)
    if marker == -1:
        return -1, 0
    end = source.find("]", marker + 2)
    if end == -1:
        return marker, 2
    if source[end + 1 : end + 2] == "[":
        reference_end = source.find("]", end + 2)
        end = end if reference_end == -1 else reference_end
    elif source[end + 1 : end + 2] == "(":
        inline_end = source.find(")", end + 2)
        end = end if inline_end == -1 else inline_end
    return marker, end + 1 - marker


def _image_warnings(root: Path, path: Path) -> list[Warning]:
    source = path.read_text(encoding="utf-8")
    warnings: list[Warning] = []
    relative_file = path.relative_to(root)
    for token in _MARKDOWN.parse(source):
        if token.type != "inline" or token.children is None:
            continue
        first_line = 1 if token.map is None else token.map[0] + 1
        content_position = 0
        for child in token.children:
            if child.type != "image" or child.attrs is None:
                continue
            src = child.attrs.get("src")
            if not isinstance(src, str):
                continue
            image_position, syntax_length = _image_position(
                token.content, content_position
            )
            line = (
                first_line + token.content.count("\n", 0, image_position)
                if image_position != -1
                else first_line
            )
            if image_position != -1:
                content_position = image_position + syntax_length

            parsed = urlsplit(src)
            if parsed.scheme or parsed.netloc:
                warnings.append(
                    _warning(
                        relative_file,
                        line,
                        f"image path is not relative: {src!r}",
                    )
                )
                continue

            image_name = unquote(parsed.path)
            try:
                image_path = Path(image_name)
                if image_path.is_absolute():
                    resolved_image = image_path.resolve(strict=False)
                    message = (
                        "image path escapes repository"
                        if not resolved_image.is_relative_to(root)
                        else "image path must be relative"
                    )
                    warnings.append(
                        _warning(relative_file, line, f"{message}: {src!r}")
                    )
                    continue
                image_path = (path.parent / image_path).resolve(strict=False)
            except OSError, RuntimeError, ValueError:
                warnings.append(
                    _warning(
                        relative_file,
                        line,
                        f"invalid image path: {src!r}",
                    )
                )
                continue

            if not image_path.is_relative_to(root):
                warnings.append(
                    _warning(
                        relative_file,
                        line,
                        f"image path escapes repository: {src!r}",
                    )
                )
            elif not image_path.is_file():
                warnings.append(
                    _warning(
                        relative_file,
                        line,
                        f"missing image: {src!r}",
                    )
                )
    return warnings


def _mark_ignored_lines(mask: list[bool], source: str, tokens: list[Token]) -> None:
    line_spans: list[tuple[int, int]] = []
    start = 0
    for line in source.splitlines(keepends=True):
        end = start + len(line)
        line_spans.append((start, end))
        start = end
    if start < len(source):
        line_spans.append((start, len(source)))

    for token in tokens:
        if token.type not in _IGNORED_TOKEN_TYPES or token.map is None:
            continue
        first, last = token.map
        for line in range(first, min(last, len(line_spans))):
            line_start, line_end = line_spans[line]
            mask[line_start:line_end] = [True] * (line_end - line_start)


def _is_escaped(source: str, position: int) -> bool:
    backslashes = 0
    position -= 1
    while position >= 0 and source[position] == "\\":
        backslashes += 1
        position -= 1
    return backslashes % 2 == 1


def _ignored_mask(source: str, tokens: list[Token]) -> list[bool]:
    """Mask code and comments so their dollar signs are not checked."""
    mask = [False] * len(source)
    _mark_ignored_lines(mask, source, tokens)
    position = 0
    while position < len(source):
        if mask[position]:
            position += 1
            continue
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
        position += 1
    return mask


def _closing_delimiter(
    source: str, start: int, delimiter: str, ignored: list[bool]
) -> int | None:
    position = start
    while position < len(source):
        if ignored[position]:
            position += 1
            continue
        if source.startswith(delimiter, position) and not _is_escaped(source, position):
            return position
        position += 1
    return None


def _math_warnings_in_text(file: Path, source: str, first_line: int) -> list[Warning]:
    ignored = _ignored_mask(source, _MARKDOWN.parse(source))
    warnings: list[Warning] = []
    position = 0
    while position < len(source):
        if ignored[position] or source[position] != "$":
            position += 1
            continue
        if _is_escaped(source, position):
            position += 1
            continue

        delimiter = "$$" if source.startswith("$$", position) else "$"
        close = _closing_delimiter(
            source, position + len(delimiter), delimiter, ignored
        )
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
    warnings: list[Warning] = []
    for token in _MARKDOWN.parse(source):
        if token.type != "inline" or token.map is None:
            continue
        warnings.extend(
            _math_warnings_in_text(
                path.relative_to(root), token.content, token.map[0] + 1
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
