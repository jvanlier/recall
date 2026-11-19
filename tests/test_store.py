"""Tests for the SQLite review store."""

import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from recall.store import Review, ReviewStore, read_jsonl

T = datetime(2026, 6, 10, 8, 12, 3, tzinfo=UTC)


def test_round_trip_normalises_to_utc_seconds(tmp_path: Path) -> None:
    path = tmp_path / "data" / "reviews.db"
    store = ReviewStore(path)

    store.append("card:fwd", datetime(2026, 6, 10, 10, 12, 3, 456789, tzinfo=timezone(timedelta(hours=2))), 3, 4200)

    assert ReviewStore(path).read() == [Review("card:fwd", T, 3, 4200)]
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT t FROM reviews").fetchone() == ("2026-06-10T08:12:03Z",)
    assert store.pending == 1


def test_undo_only_removes_reviews_from_this_process(tmp_path: Path) -> None:
    path = tmp_path / "reviews.db"
    ReviewStore(path).append("old", T, 3, 1)
    store = ReviewStore(path)
    assert store.undo_last() is None

    store.append("new", T, 4, 2)

    assert store.undo_last() == Review("new", T, 4, 2)
    assert store.pending == 0
    assert store.undo_last() is None
    assert store.read() == [Review("old", T, 3, 1)]


def test_validation_at_append_boundary(tmp_path: Path) -> None:
    store = ReviewStore(tmp_path / "reviews.db")

    with pytest.raises(ValueError, match="card ID"):
        store.append("", T, 3, 0)
    with pytest.raises(ValueError, match="rating"):
        store.append("card", T, 5, 0)
    with pytest.raises(ValueError, match="ms"):
        store.append("card", T, 3, -1)
    with pytest.raises(ValueError, match="timezone"):
        store.append("card", T.replace(tzinfo=None), 3, 0)
    assert store.read() == []


def test_legacy_log_is_imported_once_into_an_empty_database(tmp_path: Path) -> None:
    legacy = tmp_path / "reviews.jsonl"
    legacy.write_text('{"card": "card", "t": "2026-06-10T08:12:03Z", "rating": 3, "ms": 4200}\n', encoding="utf-8")
    path = tmp_path / "reviews.db"

    ReviewStore(path, legacy_log=legacy).append("next", T, 2, 1)
    store = ReviewStore(path, legacy_log=legacy)

    assert store.read() == [Review("card", T, 3, 4200), Review("next", T, 2, 1)]
    assert store.undo_last() is None


def test_read_jsonl_skips_and_warns_about_bad_lines(tmp_path: Path) -> None:
    path = tmp_path / "reviews.jsonl"
    path.write_bytes(
        b'{"relink": "old", "to": "new"}\n'
        b'{"card": "valid", "t": "2026-06-10T08:12:03Z", "rating": 4, "ms": 0, "future": true}\n'
        b"not json\n"
        b'{"card": "naive", "t": "2026-06-10T08:12:03", "rating": 3, "ms": 1}\n'
        b'{"card": "broken\xff", "t": "2026-06-10T08:12:03Z", "rating": 3, "ms": 1}\n'
        b'{"card": "card", "t": "2026-06-10T08:12:03Z", "rating": 3, "ms": 4200}'
    )

    with pytest.warns(UserWarning) as warned:
        reviews = read_jsonl(path)

    assert [str(warning.message).split(":")[0] for warning in warned] == [
        f"malformed review log line {line}" for line in (3, 4, 5)
    ]

    assert reviews == [Review("valid", T, 4, 0), Review("card", T, 3, 4200)]
    assert read_jsonl(tmp_path / "missing.jsonl") == []
