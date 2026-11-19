"""Durable review history in SQLite."""

from __future__ import annotations

import json
import sqlite3
import threading
import warnings
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY,
    card TEXT NOT NULL CHECK (card <> ''),
    t TEXT NOT NULL,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 4),
    ms INTEGER NOT NULL CHECK (ms >= 0)
)
"""


@dataclass(frozen=True, slots=True)
class Review:
    """One recorded review."""

    card: str
    t: datetime
    rating: int
    ms: int


def _validate_card(card: object) -> str:
    if not isinstance(card, str) or not card:
        raise ValueError("card ID must be a non-empty string")
    return card


def _validate_rating(rating: object) -> int:
    if type(rating) is not int or not 1 <= rating <= 4:
        raise ValueError("rating must be an integer from 1 to 4")
    return rating


def _validate_ms(ms: object) -> int:
    if type(ms) is not int or not 0 <= ms < 2**63:
        raise ValueError("ms must be a non-negative integer")
    return ms


def _parse_timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        timestamp = value
    elif isinstance(value, str):
        iso_value = f"{value[:-1]}+00:00" if value.endswith("Z") else value
        try:
            timestamp = datetime.fromisoformat(iso_value)
        except ValueError as exc:
            raise ValueError("t must be an ISO 8601 timestamp") from exc
    else:
        raise ValueError("t must be an ISO 8601 timestamp")

    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("t must be timezone-aware")
    return timestamp


def _format_timestamp(timestamp: datetime) -> str:
    return timestamp.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _review(card: object, t: object, rating: object, ms: object) -> Review:
    return Review(
        card=_validate_card(card),
        t=_parse_timestamp(t).astimezone(UTC).replace(microsecond=0),
        rating=_validate_rating(rating),
        ms=_validate_ms(ms),
    )


def read_jsonl(path: str | Path) -> list[Review]:
    """Read reviews from the legacy ``reviews.jsonl`` log, warning about bad lines."""
    try:
        file = Path(path).open("rb")
    except FileNotFoundError:
        return []
    reviews: list[Review] = []
    with file:
        for line_number, raw_line in enumerate(file, start=1):
            try:
                record = json.loads(raw_line.decode("utf-8"))
                if not isinstance(record, dict):
                    raise ValueError("expected an object")
                if "card" not in record:
                    continue
                reviews.append(_review(record["card"], record["t"], record["rating"], record["ms"]))
            except (UnicodeDecodeError, KeyError, ValueError) as exc:
                warnings.warn(f"malformed review log line {line_number}: {exc}", UserWarning, stacklevel=2)
    return reviews


class ReviewStore:
    """Read, append, and undo reviews in a SQLite database."""

    def __init__(self, path: str | Path, *, legacy_log: str | Path | None = None) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._undoable: list[tuple[int, Review]] = []
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(_SCHEMA)
            if legacy_log is not None and connection.execute("SELECT 1 FROM reviews LIMIT 1").fetchone() is None:
                connection.executemany(
                    "INSERT INTO reviews (card, t, rating, ms) VALUES (?, ?, ?, ?)",
                    [(r.card, _format_timestamp(r.t), r.rating, r.ms) for r in read_jsonl(legacy_log)],
                )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Open a connection and commit (or roll back) one transaction."""
        with self._lock, closing(sqlite3.connect(self.path)) as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
            with connection:
                yield connection

    @property
    def pending(self) -> int:
        """Return the number of reviews this process can still undo."""
        with self._lock:
            return len(self._undoable)

    def append(self, card_id: str, t: datetime, rating: int, ms: int) -> Review:
        """Validate and durably store one review."""
        review = _review(card_id, t, rating, ms)
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO reviews (card, t, rating, ms) VALUES (?, ?, ?, ?)",
                (review.card, _format_timestamp(review.t), review.rating, review.ms),
            )
            assert cursor.lastrowid is not None
            self._undoable.append((cursor.lastrowid, review))
        return review

    def read(self) -> list[Review]:
        """Return every stored review in insertion order."""
        with self._connect() as connection:
            rows = connection.execute("SELECT card, t, rating, ms FROM reviews ORDER BY id").fetchall()
        return [Review(card, _parse_timestamp(t), rating, ms) for card, t, rating, ms in rows]

    def undo_last(self) -> Review | None:
        """Delete and return the last review stored by this process, if any."""
        with self._lock:
            if not self._undoable:
                return None
            row_id, review = self._undoable[-1]
            with self._connect() as connection:
                connection.execute("DELETE FROM reviews WHERE id = ?", (row_id,))
            self._undoable.pop()
            return review
