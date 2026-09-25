"""Tests for FSRS replay and review queue selection."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from recall.log import Review, ReviewLog
from recall.parser import load_repo
from recall.scheduler import Scheduler, SchedulerConfig, load_config

NOW = datetime(2026, 6, 10, 12, tzinfo=UTC)


def parsed_repo(tmp_path: Path, source: str):
    (tmp_path / "Deck.md").write_text(source, encoding="utf-8")
    return load_repo(tmp_path)


def test_replay_is_deterministic(tmp_path: Path) -> None:
    result = parsed_repo(tmp_path, "one::1\n")
    card_id = result.cards[0].id
    reviews = [
        Review(card_id, NOW - timedelta(days=10), 3, 1000),
        Review(card_id, NOW - timedelta(days=1), 2, 900),
    ]

    first = Scheduler(result, reviews).card_state(card_id)
    second = Scheduler(result, reviews).card_state(card_id)

    assert first is not None and second is not None
    assert first.to_dict() == second.to_dict()


def test_unknown_reviews_are_ignored(tmp_path: Path) -> None:
    result = parsed_repo(tmp_path, "one::1\n")
    unknown = Review("deleted-card", NOW, 3, 100)

    scheduler = Scheduler(result, [unknown])

    assert scheduler.card_state("deleted-card") is None
    assert scheduler.next_card("all", NOW) is not None


def test_new_card_limit_is_global_across_decks(tmp_path: Path) -> None:
    (tmp_path / "A.md").write_text("one::1\n", encoding="utf-8")
    (tmp_path / "B.md").write_text("two::2\n", encoding="utf-8")
    result = load_repo(tmp_path)
    log = ReviewLog(tmp_path / ".recall" / "reviews.jsonl")
    scheduler = Scheduler(
        result,
        log=log,
        config=SchedulerConfig(new_per_day=1),
    )

    first = scheduler.next_card("all", NOW)
    assert first is not None and first.id is not None
    scheduler.record(first.id, 3, 100, NOW)

    assert scheduler.counts("B", NOW) == (0, 0)


def test_day_boundary_uses_four_am(tmp_path: Path) -> None:
    result = parsed_repo(tmp_path, "one::1\ntwo::2\n")
    first, second = result.cards
    reviews = [Review(first.id, datetime(2026, 6, 10, 3, 59, tzinfo=UTC), 3, 1)]
    scheduler = Scheduler(result, reviews, config=SchedulerConfig(new_per_day=1))

    assert scheduler.counts("all", datetime(2026, 6, 10, 3, 59, tzinfo=UTC))[1] == 0
    assert scheduler.counts("all", datetime(2026, 6, 10, 4, tzinfo=UTC))[1] == 1
    assert second.id != first.id


def test_reversible_sibling_is_buried_but_learning_card_returns(tmp_path: Path) -> None:
    result = parsed_repo(tmp_path, "front:::back\n")
    log = ReviewLog(tmp_path / ".recall" / "reviews.jsonl")
    scheduler = Scheduler(
        result,
        log=log,
        config=SchedulerConfig(learning_steps=(timedelta(minutes=1),)),
    )
    first = scheduler.next_card("all", NOW)
    assert first is not None and first.id is not None
    sibling = next(card for card in result.cards if card.id != first.id)

    scheduler.record(first.id, 1, 100, NOW)

    assert scheduler.next_card("all", NOW + timedelta(minutes=2)) == first
    assert scheduler.next_card("all", NOW + timedelta(minutes=2)) != sibling


def test_undo_replays_the_card(tmp_path: Path) -> None:
    result = parsed_repo(tmp_path, "one::1\n")
    log = ReviewLog(tmp_path / ".recall" / "reviews.jsonl")
    scheduler = Scheduler(result, log=log)
    card = scheduler.next_card("all", NOW)
    assert card is not None and card.id is not None

    scheduler.record(card.id, 3, 100, NOW)
    removed = scheduler.undo()

    assert removed == Review(card.id, NOW, 3, 100)
    assert scheduler.card_state(card.id) is None
    assert scheduler.next_card("all", NOW) == card


def test_config_defaults_and_invalid_values_warn(tmp_path: Path) -> None:
    (tmp_path / ".recall").mkdir()
    (tmp_path / ".recall" / "config.toml").write_text(
        """
        desired_retention = 2
        new_per_day = -1
        day_start_hour = 25
        unknown = true
        """,
        encoding="utf-8",
    )

    with pytest.warns(UserWarning) as caught:
        config = load_config(tmp_path)

    assert config == SchedulerConfig()
    assert len(caught) == 4


def test_config_parses_durations_and_parameters(tmp_path: Path) -> None:
    (tmp_path / ".recall").mkdir()
    (tmp_path / ".recall" / "config.toml").write_text(
        """
        desired_retention = 0.85
        learning_steps = ["1m", "2h"]
        relearning_steps = []
        new_per_day = 7
        day_start_hour = 3
        learn_ahead_minutes = 5
        """,
        encoding="utf-8",
    )

    config = load_config(tmp_path)

    assert config.desired_retention == 0.85
    assert config.learning_steps == (timedelta(minutes=1), timedelta(hours=2))
    assert config.relearning_steps == ()
    assert config.new_per_day == 7
    assert config.day_start_hour == 3
    assert config.learn_ahead_minutes == 5
