"""Stable card IDs: changing this scheme orphans all review history."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict

from recall.cards import Card, Warning

_PINNED_ID = re.compile(r"^[a-z0-9-]+$")


def normalize(text: str) -> str:
    """Normalize card text before it is used as an ID input."""
    return " ".join(text.split())


def _hash(text: str, length: int) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()[:length]


def _base_id(card: Card) -> str:
    if card.pinned_id is not None:
        return card.pinned_id
    return _hash(card.raw_text, 12)


def card_id(card: Card) -> str:
    """Return the stable ID for *card*.

    Invalid pinned IDs are rejected by :func:`assign_ids` before this function
    is called for cards loaded from a repository.
    """
    base = _base_id(card)
    if card.kind == "reverse-fwd":
        return f"{base}:fwd"
    if card.kind == "reverse-rev":
        return f"{base}:rev"
    if card.kind == "cloze":
        if card.cloze_deleted is None:
            raise ValueError("cloze card has no deleted text")
        return f"{base}:{_hash(card.cloze_deleted, 8)}"
    return base


def _location(card: Card) -> str:
    return f"{card.file}:{card.line}"


def assign_ids(cards: list[Card], warnings: list[Warning]) -> list[Card]:
    """Assign IDs, warn about invalid pins and duplicates, and skip failures."""
    valid: list[Card] = []
    for card in cards:
        if card.pinned_id is not None and not _PINNED_ID.fullmatch(card.pinned_id):
            warnings.append(
                Warning(
                    file=card.file,
                    line=card.line,
                    message=(
                        f"invalid pinned ID {card.pinned_id!r}; card skipped "
                        "(use only lowercase letters, digits, and hyphens)"
                    ),
                )
            )
            continue
        card.id = card_id(card)
        card.sibling_key = _base_id(card)
        valid.append(card)

    by_id: dict[str, list[Card]] = defaultdict(list)
    for card in valid:
        identifier = card.id
        assert identifier is not None
        by_id[identifier].append(card)

    duplicate_ids: set[str] = set()
    for identifier, group in by_id.items():
        if len(group) == 1:
            continue
        duplicate_ids.add(identifier)
        locations = ", ".join(_location(card) for card in group)
        first = group[0]
        warnings.append(
            Warning(
                file=first.file,
                line=first.line,
                message=f"duplicate card ID {identifier!r}; locations: {locations}",
            )
        )

    return [card for card in valid if card.id not in duplicate_ids]
