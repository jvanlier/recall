"""Durable, append-only review history."""

from __future__ import annotations

import json
import os
import threading
import warnings
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class Review:
    """One review recorded in the review log."""

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
    if type(ms) is not int or ms < 0:
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
    return (
        timestamp.astimezone(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _review_from_record(record: dict[str, Any]) -> Review:
    return Review(
        card=_validate_card(record["card"]),
        t=_parse_timestamp(record["t"]),
        rating=_validate_rating(record["rating"]),
        ms=_validate_ms(record["ms"]),
    )


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    file_descriptor = os.open(path, flags)
    try:
        os.fsync(file_descriptor)
    finally:
        os.close(file_descriptor)


class ReviewLog:
    """Read and durably append reviews in a JSON Lines file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._pending_separators: list[bool] = []

    @property
    def pending(self) -> int:
        """Return the number of reviews appended since the last commit mark."""
        with self._lock:
            return len(self._pending_separators)

    def append(
        self,
        card_id: str,
        t: datetime,
        rating: int,
        ms: int,
    ) -> None:
        """Validate and durably append one review."""
        review = Review(
            card=_validate_card(card_id),
            t=_parse_timestamp(t),
            rating=_validate_rating(rating),
            ms=_validate_ms(ms),
        )
        payload = {
            "card": review.card,
            "t": _format_timestamp(review.t),
            "rating": review.rating,
            "ms": review.ms,
        }
        encoded = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")

        with self._lock:
            parent = self.path.parent
            new_directories: list[Path] = []
            existing_directory = parent
            while not existing_directory.exists():
                new_directories.append(existing_directory)
                existing_directory = existing_directory.parent
            parent.mkdir(parents=True, exist_ok=True)
            directories_to_sync = [parent, *new_directories[1:]]
            if new_directories:
                directories_to_sync.append(existing_directory)

            with self.path.open("a+b") as file:
                file.seek(0, os.SEEK_END)
                needs_separator = file.tell() > 0
                if needs_separator:
                    file.seek(-1, os.SEEK_END)
                    needs_separator = file.read(1) != b"\n"
                    file.seek(0, os.SEEK_END)
                    if needs_separator:
                        file.write(b"\n")
                file.write(encoded)
                file.flush()
                os.fsync(file.fileno())
            for directory in directories_to_sync:
                _fsync_directory(directory)
            self._pending_separators.append(needs_separator)

    def read(self) -> list[Review]:
        """Read valid review records, warning about malformed lines."""
        with self._lock:
            try:
                file = self.path.open("rb")
            except FileNotFoundError:
                return []

            reviews: list[Review] = []
            with file:
                for line_number, raw_line in enumerate(file, start=1):
                    try:
                        line = raw_line.decode("utf-8")
                    except UnicodeDecodeError as exc:
                        warnings.warn(
                            f"malformed review log line {line_number}: "
                            f"invalid UTF-8 ({exc})",
                            UserWarning,
                            stacklevel=2,
                        )
                        continue
                    try:
                        record = json.loads(line)
                    except (json.JSONDecodeError, ValueError) as exc:
                        warnings.warn(
                            f"malformed review log line {line_number}: {exc}",
                            UserWarning,
                            stacklevel=2,
                        )
                        continue
                    if not isinstance(record, dict):
                        warnings.warn(
                            f"malformed review log line {line_number}: "
                            "expected an object",
                            UserWarning,
                            stacklevel=2,
                        )
                        continue
                    if "card" not in record:
                        continue
                    try:
                        reviews.append(_review_from_record(record))
                    except (KeyError, ValueError) as exc:
                        warnings.warn(
                            f"malformed review log line {line_number}: {exc}",
                            UserWarning,
                            stacklevel=2,
                        )
            return reviews

    def undo_last(self) -> Review | None:
        """Remove and return the last uncommitted review, if there is one."""
        with self._lock:
            if not self._pending_separators:
                return None

            try:
                data = self.path.read_bytes()
            except FileNotFoundError:
                return None
            if not data:
                return None

            content_end = len(data) - 1 if data.endswith(b"\n") else len(data)
            line_start = data.rfind(b"\n", 0, content_end) + 1
            try:
                record = json.loads(data[line_start:content_end].decode("utf-8"))
                if not isinstance(record, dict) or "card" not in record:
                    return None
                review = _review_from_record(record)
            except UnicodeDecodeError, json.JSONDecodeError, KeyError, ValueError:
                return None

            separator_added = self._pending_separators[-1]
            truncate_at = line_start - 1 if separator_added else line_start
            with self.path.open("r+b") as file:
                file.truncate(truncate_at)
                file.flush()
                os.fsync(file.fileno())
            self._pending_separators.pop()
            return review

    def mark_committed(self) -> None:
        """Forget which reviews are eligible for undo after a successful sync."""
        with self._lock:
            self._pending_separators.clear()
