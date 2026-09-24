"""Parse a cards repository into deterministic decks and cards."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from markdown_it.token import Token

from recall.cards import Card, ParseResult, Warning
from recall.markdown import markdown_it

_MARKDOWN = markdown_it()


@dataclass(frozen=True, slots=True)
class _Comment:
    start: int
    end: int
    content: str


@dataclass(frozen=True, slots=True)
class _Cloze:
    start: int
    end: int
    text: str
    hint: str | None
    hint_end: int


def _protected_lines(tokens: Iterable[Token]) -> set[int]:
    protected: set[int] = set()
    for token in tokens:
        if token.map is None or token.type not in {
            "code_block",
            "fence",
            "math_block",
            "math_block_label",
        }:
            continue
        protected.update(range(token.map[0], token.map[1]))
    return protected


def _is_escaped(source: str, position: int) -> bool:
    backslashes = 0
    position -= 1
    while position >= 0 and source[position] == "\\":
        backslashes += 1
        position -= 1
    return backslashes % 2 == 1


def _mark_interval(mask: list[bool], start: int, end: int) -> None:
    mask[start:end] = [True] * (end - start)


def _semantic_mask(
    source: str, protected_lines: set[int]
) -> tuple[list[bool], list[_Comment]]:
    """Mask code, math, and comments from card syntax recognition."""
    mask = [False] * len(source)
    comments: list[_Comment] = []
    line = 0
    position = 0
    while position < len(source):
        if source[position] == "\n":
            line += 1
            position += 1
            continue
        if line in protected_lines:
            mask[position] = True
            position += 1
            continue

        if source.startswith("<!--", position):
            end_marker = source.find("-->", position + 4)
            end = len(source) if end_marker == -1 else end_marker + 3
            _mark_interval(mask, position, end)
            comments.append(_Comment(position, end, source[position:end]))
            line += source[position:end].count("\n")
            position = end
            continue

        if source[position] == "`":
            run_end = position
            while run_end < len(source) and source[run_end] == "`":
                run_end += 1
            delimiter = source[position:run_end]
            close = source.find(delimiter, run_end)
            if close != -1:
                end = close + len(delimiter)
                _mark_interval(mask, position, end)
                line += source[position:end].count("\n")
                position = end
                continue

        if source[position] == "$" and not _is_escaped(source, position):
            delimiter = "$$" if source.startswith("$$", position) else "$"
            close = source.find(delimiter, position + len(delimiter))
            while close != -1 and _is_escaped(source, close):
                close = source.find(delimiter, close + len(delimiter))
            if close != -1:
                end = close + len(delimiter)
                _mark_interval(mask, position, end)
                line += source[position:end].count("\n")
                position = end
                continue

        position += 1

    return mask, comments


def _strip_comments(source: str, comments: Iterable[_Comment]) -> str:
    remove = [False] * len(source)
    for comment in comments:
        remove[comment.start : comment.end] = [True] * (comment.end - comment.start)
    return "".join(
        " " if remove[index] and character != "\n" else character
        for index, character in enumerate(source)
    )


def _comment_body(comment: _Comment) -> str:
    body = (
        comment.content[4:-3]
        if comment.content.endswith("-->")
        else comment.content[4:]
    )
    return body.strip()


def _is_hide(comment: _Comment) -> bool:
    return _comment_body(comment) == "hide"


def _pinned_id(comments: Iterable[_Comment]) -> str | None:
    for comment in comments:
        body = _comment_body(comment)
        if body.startswith("id:"):
            return body[3:].strip()
    return None


def _line_spans(source: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    for line in source.splitlines(keepends=True):
        end = start + len(line)
        spans.append((start, end))
        start = end
    if start < len(source):
        spans.append((start, len(source)))
    return spans


def _masked(source: str, mask: list[bool]) -> str:
    return "".join(
        " " if mask[index] and character != "\n" else character
        for index, character in enumerate(source)
    )


def _line_number(source: str, offset: int, first_line: int) -> int:
    return first_line + source.count("\n", 0, offset) + 1


def _find_clozes(source: str, mask: list[bool]) -> list[_Cloze]:
    visible = _masked(source, mask)
    result: list[_Cloze] = []
    position = 0
    while True:
        start = visible.find("==", position)
        while start != -1 and _is_escaped(source, start):
            start = visible.find("==", start + 2)
        if start == -1:
            return result
        end = visible.find("==", start + 2)
        while end != -1 and (
            _is_escaped(source, end) or not visible[start + 2 : end].strip()
        ):
            end = visible.find("==", end + 2)
        if end == -1:
            return result

        hint: str | None = None
        hint_end = end + 2
        hint_start = end + 2
        if visible[hint_start : hint_start + 2] == "^[":
            close_hint = visible.find("]", hint_start + 2)
            if close_hint != -1:
                hint = source[hint_start + 2 : close_hint]
                hint_end = close_hint + 1

        result.append(
            _Cloze(
                start=start,
                end=end + 2,
                text=source[start + 2 : end],
                hint=hint,
                hint_end=hint_end,
            )
        )
        position = hint_end


def _remove_cloze_syntax(source: str, clozes: Iterable[_Cloze]) -> str:
    remove = [False] * len(source)
    for cloze in clozes:
        remove[cloze.start : cloze.start + 2] = [True, True]
        remove[cloze.end - 2 : cloze.end] = [True, True]
        remove[cloze.end : cloze.hint_end] = [True] * (cloze.hint_end - cloze.end)
    return "".join(
        character for index, character in enumerate(source) if not remove[index]
    )


def _mark_count(tokens: Iterable[Token]) -> int:
    count = 0
    for token in tokens:
        if token.type != "inline" or token.children is None:
            continue
        count += sum(child.type == "mark_open" for child in token.children)
    return count


def _warning(warnings: list[Warning], file: Path, line: int, message: str) -> None:
    warnings.append(Warning(file=file, line=line, message=message))


def _card(
    *,
    deck: str,
    file: Path,
    line: int,
    kind: str,
    front: str,
    back: str,
    block: int,
    hidden: bool,
    pinned_id: str | None,
    raw_text: str,
    cloze_text: str | None = None,
    cloze_index: int | None = None,
    cloze_hint: str | None = None,
) -> Card:
    return Card(
        deck=deck,
        file=file,
        line=line,
        kind=kind,
        front=front,
        back=back,
        block=block,
        hidden=hidden,
        pinned_id=pinned_id,
        raw_text=raw_text,
        cloze_text=cloze_text,
        cloze_index=cloze_index,
        cloze_hint=cloze_hint,
    )


def _parse_block(
    *,
    source: str,
    first_line: int,
    deck: str,
    file: Path,
    block: int,
    protected_lines: set[int],
    warnings: list[Warning],
) -> list[Card]:
    block_tokens = _MARKDOWN.parse(source)
    local_protected = {
        line - first_line for line in protected_lines if first_line <= line
    }
    _, comments = _semantic_mask(source, local_protected)
    clean = _strip_comments(source, comments)
    mask, _ = _semantic_mask(clean, local_protected)
    visible = _masked(clean, mask)
    spans = _line_spans(clean)
    lines = [clean[start:end] for start, end in spans]
    semantic_lines = [visible[start:end] for start, end in spans]
    hidden_comments = [comment for comment in comments if _is_hide(comment)]
    block_hidden = bool(hidden_comments)

    marker_line: tuple[int, str] | None = None
    for index, line in enumerate(semantic_lines):
        if line.strip() in {"?", "??"}:
            marker_line = (index, line.strip())
            break

    if marker_line is not None:
        index, marker = marker_line
        front = "".join(lines[:index]).strip()
        back = "".join(lines[index + 1 :]).strip()
        card_line = first_line + index + 1
        if not front or not back:
            _warning(
                warnings,
                file,
                card_line,
                "card has an empty front or back",
            )
            return []
        pinned = _pinned_id(comments)
        kind = "reverse-fwd" if marker == "??" else "basic"
        cards = [
            _card(
                deck=deck,
                file=file,
                line=card_line,
                kind=kind,
                front=front,
                back=back,
                block=block,
                hidden=block_hidden,
                pinned_id=pinned,
                raw_text=front,
            )
        ]
        if marker == "??":
            cards.append(
                _card(
                    deck=deck,
                    file=file,
                    line=card_line,
                    kind="reverse-rev",
                    front=back,
                    back=front,
                    block=block,
                    hidden=block_hidden,
                    pinned_id=pinned,
                    raw_text=front,
                )
            )
        return cards

    mark_count = _mark_count(block_tokens)
    clozes = _find_clozes(clean, mask)
    if mark_count or clozes:
        if not clozes:
            marker = visible.find("==")
            _warning(
                warnings,
                file,
                _line_number(clean, max(marker, 0), first_line),
                "cloze block has no valid deletions",
            )
            return []
        full_text = clean.strip()
        raw_text = _remove_cloze_syntax(clean, clozes).strip()
        cards = []
        for index, cloze in enumerate(clozes):
            cards.append(
                _card(
                    deck=deck,
                    file=file,
                    line=_line_number(clean, cloze.start, first_line),
                    kind="cloze",
                    front=full_text,
                    back=full_text,
                    block=block,
                    hidden=block_hidden,
                    pinned_id=_pinned_id(comments),
                    raw_text=raw_text,
                    cloze_text=full_text,
                    cloze_index=index,
                    cloze_hint=cloze.hint,
                )
            )
        return cards

    if "==" in visible:
        marker = visible.find("==")
        _warning(
            warnings,
            file,
            _line_number(clean, max(marker, 0), first_line),
            "cloze block has no valid deletions",
        )
        return []

    cards: list[Card] = []
    candidate_lines = {
        index for index, line in enumerate(semantic_lines) if "::" in line
    }
    line_hidden: set[int] = set()
    block_hidden_for_lines = False
    for comment in hidden_comments:
        matching_lines = {
            index
            for index, (line_start, line_end) in enumerate(spans)
            if comment.start < line_end and comment.end > line_start
        }
        matching_candidates = matching_lines & candidate_lines
        if matching_candidates:
            line_hidden.update(matching_candidates)
        else:
            block_hidden_for_lines = True

    for index in sorted(candidate_lines):
        semantic_line = semantic_lines[index].rstrip("\r\n")
        marker = ":::" if ":::" in semantic_line else "::"
        marker_position = semantic_line.find(marker)
        if marker_position == -1:
            continue
        raw_line = lines[index].rstrip("\r\n")
        front = raw_line[:marker_position].strip()
        back = raw_line[marker_position + len(marker) :].strip()
        line_start = spans[index][0]
        line_end = spans[index][1]
        line_comments = [
            comment
            for comment in comments
            if comment.start < line_end and comment.end > line_start
        ]
        hidden = block_hidden_for_lines or index in line_hidden
        pinned = _pinned_id(line_comments)
        if marker == ":::":
            cards.extend(
                [
                    _card(
                        deck=deck,
                        file=file,
                        line=first_line + index + 1,
                        kind="reverse-fwd",
                        front=front,
                        back=back,
                        block=block,
                        hidden=hidden,
                        pinned_id=pinned,
                        raw_text=front,
                    ),
                    _card(
                        deck=deck,
                        file=file,
                        line=first_line + index + 1,
                        kind="reverse-rev",
                        front=back,
                        back=front,
                        block=block,
                        hidden=hidden,
                        pinned_id=pinned,
                        raw_text=front,
                    ),
                ]
            )
        else:
            cards.append(
                _card(
                    deck=deck,
                    file=file,
                    line=first_line + index + 1,
                    kind="single-line",
                    front=front,
                    back=back,
                    block=block,
                    hidden=hidden,
                    pinned_id=pinned,
                    raw_text=front,
                )
            )
    return cards


def _parse_file(root: Path, path: Path) -> tuple[list[Card], list[Warning]]:
    relative = path.relative_to(root)
    file = relative
    deck = relative.with_suffix("").as_posix()
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines(keepends=True)
    if not lines and source:
        lines = [source]
    tokens = _MARKDOWN.parse(source)
    protected_lines = _protected_lines(tokens)
    warnings: list[Warning] = []
    for token in tokens:
        if (
            token.type == "heading_open"
            and token.markup == "-"
            and token.map is not None
        ):
            _warning(
                warnings,
                file,
                token.map[1],
                "missing blank line before thematic break",
            )

    separators = [
        token.map for token in tokens if token.type == "hr" and token.map is not None
    ]
    ranges: list[tuple[int, int]] = []
    start = 0
    for separator in separators:
        end = separator[0]
        if start < end:
            ranges.append((start, end))
        start = separator[1]
    if start < len(lines):
        ranges.append((start, len(lines)))

    cards: list[Card] = []
    for block, (block_start, block_end) in enumerate(ranges):
        cards.extend(
            _parse_block(
                source="".join(lines[block_start:block_end]),
                first_line=block_start,
                deck=deck,
                file=file,
                block=block,
                protected_lines=protected_lines,
                warnings=warnings,
            )
        )
    return cards, warnings


def _is_hidden_path(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    return any(part.startswith(".") for part in relative.parent.parts)


def load_repo(root: Path) -> ParseResult:
    """Parse all visible markdown decks below *root*.

    Files and cards are ordered by their repository-relative path and source
    line.  No repository state is written or inferred while parsing.
    """
    root = Path(root)
    paths = sorted(
        (
            path
            for path in root.rglob("*.md")
            if path.is_file() and not _is_hidden_path(path, root)
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    )

    cards: list[Card] = []
    warnings: list[Warning] = []
    decks: list[str] = []
    for path in paths:
        file_cards, file_warnings = _parse_file(root, path)
        if file_cards:
            decks.append(path.relative_to(root).with_suffix("").as_posix())
            cards.extend(file_cards)
        warnings.extend(file_warnings)
    return ParseResult(decks=decks, cards=cards, warnings=warnings)
