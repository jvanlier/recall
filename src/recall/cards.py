"""Data structures produced by the markdown card parser."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Warning:
    """A parser warning located in a cards repository."""

    file: Path
    line: int
    message: str


@dataclass(slots=True)
class Card:
    """One reviewable card and its source location."""

    deck: str
    file: Path
    line: int
    kind: str
    front: str
    back: str
    block: int
    hidden: bool = False
    pinned_id: str | None = None
    raw_text: str = ""
    cloze_text: str | None = None
    cloze_index: int | None = None
    cloze_hint: str | None = None
    id: str | None = None
    sibling_key: str | None = None

    @property
    def full_text(self) -> str | None:
        """Return the source text for a cloze card."""
        return self.cloze_text

    @property
    def deletion_index(self) -> int | None:
        """Return the zero-based deletion index for a cloze card."""
        return self.cloze_index

    @property
    def hint(self) -> str | None:
        """Return the optional cloze hint."""
        return self.cloze_hint


@dataclass(slots=True)
class ParseResult:
    """The deterministic result of parsing one cards repository."""

    decks: list[str]
    cards: list[Card]
    warnings: list[Warning]


# A descriptive alias for callers that prefer not to import a generic name.
ParseWarning = Warning
