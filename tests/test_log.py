"""Tests for the durable review log."""

import json
import os
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from recall.log import Review, ReviewLog


def test_round_trip_of_append_and_read(tmp_path: Path) -> None:
    path = tmp_path / ".recall" / "reviews.jsonl"
    log = ReviewLog(path)
    timestamp = datetime(2026, 6, 10, 10, 12, 3, 456789, tzinfo=UTC)

    log.append("card-id:fwd", timestamp, 3, 4200)

    assert path.read_text(encoding="utf-8") == (
        '{"card": "card-id:fwd", "t": "2026-06-10T10:12:03Z", '
        '"rating": 3, "ms": 4200}\n'
    )
    assert log.read() == [
        Review(
            card="card-id:fwd",
            t=datetime(2026, 6, 10, 10, 12, 3, tzinfo=UTC),
            rating=3,
            ms=4200,
        )
    ]
    assert log.pending == 1


def test_append_normalizes_timezone_to_utc(tmp_path: Path) -> None:
    path = tmp_path / "reviews.jsonl"
    log = ReviewLog(path)

    log.append(
        "card",
        datetime(2026, 6, 10, 10, 12, 3, tzinfo=timezone(timedelta(hours=2))),
        1,
        0,
    )

    assert json.loads(path.read_text(encoding="utf-8"))["t"] == "2026-06-10T08:12:03Z"


def test_append_fsyncs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "reviews.jsonl"
    log = ReviewLog(path)
    calls: list[int] = []
    real_fsync = os.fsync

    def fsync(file_descriptor: int) -> None:
        calls.append(file_descriptor)
        real_fsync(file_descriptor)

    monkeypatch.setattr("recall.log.os.fsync", fsync)

    log.append("card", datetime.now(UTC), 2, 100)

    assert len(calls) >= 2


def test_undo_when_pending_is_zero_changes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "reviews.jsonl"
    path.write_text(
        '{"card": "card", "t": "2026-06-10T08:12:03Z", "rating": 3, "ms": 1}\n'
    )
    log = ReviewLog(path)
    before = path.read_bytes()

    assert log.undo_last() is None
    assert path.read_bytes() == before


def test_undo_after_append(tmp_path: Path) -> None:
    path = tmp_path / "reviews.jsonl"
    log = ReviewLog(path)
    timestamp = datetime(2026, 6, 10, 8, 12, 3, tzinfo=UTC)
    log.append("card", timestamp, 3, 4200)

    assert log.undo_last() == Review("card", timestamp, 3, 4200)
    assert path.read_bytes() == b""
    assert log.pending == 0
    assert log.undo_last() is None


def test_undo_restores_file_without_trailing_newline(tmp_path: Path) -> None:
    path = tmp_path / "reviews.jsonl"
    path.write_bytes(
        b'{"card": "old", "t": "2026-06-10T08:12:03Z", "rating": 3, "ms": 1}'
    )
    log = ReviewLog(path)
    log.append("new", datetime(2026, 6, 10, 8, 12, 4, tzinfo=UTC), 4, 2)

    log.undo_last()

    assert path.read_bytes() == (
        b'{"card": "old", "t": "2026-06-10T08:12:03Z", "rating": 3, "ms": 1}'
    )


def test_malformed_and_unknown_lines(tmp_path: Path) -> None:
    path = tmp_path / "reviews.jsonl"
    path.write_text(
        "\n".join(
            [
                '{"relink": "old", "to": "new"}',
                (
                    '{"card": "valid", "t": "2026-06-10T08:12:03Z", '
                    '"rating": 4, "ms": 0, "future": true}'
                ),
                "not json",
                '{"card": "invalid", "t": "2026-06-10T08:12:03", "rating": 3, "ms": 1}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.warns(UserWarning, match=r"line 3"):
        reviews = ReviewLog(path).read()

    assert reviews == [
        Review("valid", datetime(2026, 6, 10, 8, 12, 3, tzinfo=UTC), 4, 0)
    ]


def test_invalid_utf8_is_warned_and_skipped(tmp_path: Path) -> None:
    path = tmp_path / "reviews.jsonl"
    path.write_bytes(
        b'{"card": "broken\xff", "t": "2026-06-10T08:12:03Z", "rating": 3, "ms": 1}\n'
    )

    with pytest.warns(UserWarning, match=r"line 1.*UTF-8"):
        assert ReviewLog(path).read() == []


def test_huge_integer_is_warned_and_skipped(tmp_path: Path) -> None:
    path = tmp_path / "reviews.jsonl"
    path.write_text(
        '{"card": "card", "t": "2026-06-10T08:12:03Z", "rating": 3, "ms": '
        + "9" * 5000
        + "}\n",
        encoding="utf-8",
    )

    with pytest.warns(UserWarning, match=r"line 1"):
        assert ReviewLog(path).read() == []


def test_file_without_trailing_newline(tmp_path: Path) -> None:
    path = tmp_path / "reviews.jsonl"
    path.write_text(
        '{"card": "card", "t": "2026-06-10T08:12:03Z", "rating": 3, "ms": 4200}',
        encoding="utf-8",
    )

    assert ReviewLog(path).read() == [
        Review("card", datetime(2026, 6, 10, 8, 12, 3, tzinfo=UTC), 3, 4200)
    ]


def test_validation_at_append_boundary(tmp_path: Path) -> None:
    log = ReviewLog(tmp_path / "reviews.jsonl")
    timestamp = datetime(2026, 6, 10, 8, 12, 3, tzinfo=UTC)

    with pytest.raises(ValueError, match="card ID"):
        log.append("", timestamp, 3, 0)
    with pytest.raises(ValueError, match="rating"):
        log.append("card", timestamp, 5, 0)
    with pytest.raises(ValueError, match="ms"):
        log.append("card", timestamp, 3, -1)
    with pytest.raises(ValueError, match="timezone"):
        log.append("card", timestamp.replace(tzinfo=None), 3, 0)
