"""Tests for the SQLite review store."""

import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from recall.store import Review, ReviewStore

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
