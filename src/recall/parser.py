"""Parse a cards repository into deterministic decks and cards."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from markdown_it.token import Token

from recall.cards import Card, ParseResult, Warning
from recall.ids import assign_ids
from recall.markdown import code_span_end, markdown_it, math_span_end

_MARKDOWN = markdown_it()


@dataclass(frozen=True, slots=True)
class _Comment:
    start: int
    end: int
    content: str


@dataclass(frozen=True, slots=True)
class ClozeSpan:
    """The source offsets of one parsed cloze deletion."""

    start: int
    end: int
    hint_start: int | None
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


def _semantic_mask(source: str, protected_lines: set[int]) -> tuple[list[bool], list[_Comment]]:
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
            end = code_span_end(source, position)
            if end is not None:
                _mark_interval(mask, position, end)
                line += source[position:end].count("\n")
                position = end
                continue

        if source[position] == "$":
            end = math_span_end(source, position)
            if end is not None:
                _mark_interval(mask, position, end)
                line += source[position:end].count("\n")
                position = end
                continue

        position += 1

    return mask, comments


def _comment_body(comment: _Comment) -> str:
    body = comment.content[4:-3] if comment.content.endswith("-->") else comment.content[4:]
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
    return "".join(" " if mask[index] and character != "\n" else character for index, character in enumerate(source))


def _line_number(source: str, offset: int, first_line: int) -> int:
    return first_line + source.count("\n", 0, offset) + 1


def _find_clozes(source: str, mask: list[bool]) -> list[ClozeSpan]:
    visible = _masked(source, mask)
    result: list[ClozeSpan] = []
    position = 0
    while True:
        start = visible.find("==", position)
        while start != -1 and _is_escaped(source, start):
            start = visible.find("==", start + 2)
        if start == -1:
            return result
        end = visible.find("==", start + 2)
        while end != -1 and (_is_escaped(source, end) or not source[start + 2 : end].strip()):
            end = visible.find("==", end + 2)
        if end == -1:
            return result

        hint_start: int | None = None
        hint_end = end + 2
        if visible[end + 2 : end + 4] == "^[":
            close_hint = visible.find("]", end + 4)
            if close_hint != -1:
                hint_start = end + 4
                hint_end = close_hint + 1

        result.append(
            ClozeSpan(
                start=start,
                end=end + 2,
                hint_start=hint_start,
                hint_end=hint_end,
            )
        )
        position = hint_end


def find_cloze_spans(source: str, mask: list[bool] | None = None) -> list[ClozeSpan]:
    """Return cloze spans using the parser's syntax-aware tokenization.

    Callers rendering already-parsed card text can omit *mask*.  The parser
    passes its existing mask so comments and protected source ranges retain
    their original offsets.
    """
    if mask is None:
        tokens = _MARKDOWN.parse(source)
        protected_lines = _protected_lines(tokens)
        mask, _ = _semantic_mask(source, protected_lines)
    return _find_clozes(source, mask)


def _comment_mask(length: int, comments: Iterable[_Comment]) -> list[bool]:
    mask = [False] * length
    for comment in comments:
        _mark_interval(mask, comment.start, comment.end)
    return mask


def _kept(source: str, removed: list[bool], start: int = 0, end: int | None = None) -> str:
    """Return ``source[start:end]`` without the characters marked *removed*."""
    end = len(source) if end is None else end
    return "".join(character for index, character in enumerate(source[start:end], start) if not removed[index])


def _without_cloze_syntax(removed: list[bool], clozes: Iterable[ClozeSpan]) -> list[bool]:
    removed = removed.copy()
    for cloze in clozes:
        _mark_interval(removed, cloze.start, cloze.start + 2)
        _mark_interval(removed, cloze.end - 2, cloze.hint_end)
    return removed


def _mark_contents(tokens: Iterable[Token]) -> list[str]:
    contents: list[str] = []
    for token in tokens:
        if token.type != "inline" or token.children is None:
            continue
        children = token.children
        for index, child in enumerate(children):
            if child.type != "mark_open":
                continue
            end = next(
                (
                    close_index
                    for close_index in range(index + 1, len(children))
                    if children[close_index].type == "mark_close"
                ),
                None,
            )
            if end is not None:
                contents.append("".join(item.content for item in children[index + 1 : end]))
    return contents


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
    cloze_deleted: str | None = None,
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
        cloze_deleted=cloze_deleted,
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
    local_protected = {line - first_line for line in protected_lines if first_line <= line}
    _, comments = _semantic_mask(source, local_protected)
    # *clean* blanks comments in place so offsets match *source* for parsing;
    # card text is taken from *source* with the comment characters removed.
    in_comment = _comment_mask(len(source), comments)
    clean = _masked(source, in_comment)
    mask, _ = _semantic_mask(clean, local_protected)
    visible = _masked(clean, mask)
    spans = _line_spans(clean)
    semantic_lines = [visible[start:end] for start, end in spans]
    hidden_comments = [comment for comment in comments if _is_hide(comment)]
    block_hidden = bool(hidden_comments)

    marker_line: tuple[int, str] | None = None
    for marker in ("??", "?"):
        for index, line in enumerate(semantic_lines):
            if line.strip() == marker:
                marker_line = (index, marker)
                break
        if marker_line is not None:
            break

    if marker_line is not None:
        index, marker = marker_line
        front = _kept(source, in_comment, 0, spans[index][0]).strip()
        back = _kept(source, in_comment, spans[index][1]).strip()
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

    mark_contents = _mark_contents(block_tokens)
    clozes = find_cloze_spans(clean, mask)
    # Tokens come from the original source; comments are blanked in *clean*
    # without shifting offsets, so compare against the same source text.
    valid_clozes = len(mark_contents) == len(clozes) and all(
        content == source[cloze.start + 2 : cloze.end - 2] for content, cloze in zip(mark_contents, clozes, strict=True)
    )
    if mark_contents or clozes:
        if not valid_clozes:
            marker = clozes[0].start if clozes else visible.find("==")
            _warning(
                warnings,
                file,
                _line_number(clean, max(marker, 0), first_line),
                "cloze block has no valid deletions",
            )
            return []
        full_text = _kept(source, in_comment).strip()
        raw_text = _kept(source, _without_cloze_syntax(in_comment, clozes)).strip()
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
                    cloze_hint=None
                    if cloze.hint_start is None
                    else _kept(source, in_comment, cloze.hint_start, cloze.hint_end - 1),
                    cloze_deleted=_kept(source, in_comment, cloze.start + 2, cloze.end - 2),
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
    candidate_lines = {index for index, line in enumerate(semantic_lines) if "::" in line}
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
        line_start = spans[index][0]
        line_end = spans[index][1]
        marker_start = line_start + marker_position
        front = _kept(source, in_comment, line_start, marker_start).strip()
        back = _kept(source, in_comment, marker_start + len(marker), line_end).strip()
        line_comments = [comment for comment in comments if comment.start < line_end and comment.end > line_start]
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
        if token.type == "heading_open" and token.markup == "-" and token.map is not None:
            _warning(
                warnings,
                file,
                token.map[1],
                "missing blank line before thematic break",
            )

    separators = [token.map for token in tokens if token.type == "hr" and token.map is not None]
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


def markdown_files(root: Path) -> list[Path]:
    """Return visible markdown files below *root* in repository order."""
    root = Path(root)
    return sorted(
        (path for path in root.rglob("*.md") if path.is_file() and not _is_hidden_path(path, root)),
        key=lambda path: path.relative_to(root).as_posix(),
    )


def load_repo(root: Path) -> ParseResult:
    """Parse all visible markdown decks below *root*.

    Files and cards are ordered by their repository-relative path and source
    line.  No repository state is written or inferred while parsing.
    """
    root = Path(root)
    paths = markdown_files(root)

    cards: list[Card] = []
    warnings: list[Warning] = []
    for path in paths:
        file_cards, file_warnings = _parse_file(root, path)
        cards.extend(file_cards)
        warnings.extend(file_warnings)

    cards = assign_ids(cards, warnings)
    decks = list(dict.fromkeys(card.deck for card in cards))
    return ParseResult(decks=decks, cards=cards, warnings=warnings)
