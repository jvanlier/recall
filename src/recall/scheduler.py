"""Replay review history through FSRS and build review queues."""

from __future__ import annotations

import hashlib
import math
import os
import random
import re
import tomllib
import warnings
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fsrs import Card as FsrsCard
from fsrs import Rating as FsrsRating
from fsrs import Scheduler as FsrsScheduler
from fsrs import State as FsrsState

from recall.cards import Card, ParseResult
from recall.log import Review, ReviewLog

_DEFAULT_LEARNING_STEPS = (timedelta(minutes=1), timedelta(minutes=10))
_DEFAULT_RELEARNING_STEPS = (timedelta(minutes=10),)
_DURATION = re.compile(r"([1-9][0-9]*)([smhd])\Z")
_CONFIG_KEYS = {
    "desired_retention",
    "parameters",
    "learning_steps",
    "relearning_steps",
    "new_per_day",
    "day_start_hour",
    "learn_ahead_minutes",
}


@dataclass(frozen=True, slots=True)
class SchedulerConfig:
    """Scheduler settings loaded from ``.recall/config.toml``."""

    desired_retention: float = 0.9
    parameters: tuple[float, ...] | None = None
    learning_steps: tuple[timedelta, ...] = _DEFAULT_LEARNING_STEPS
    relearning_steps: tuple[timedelta, ...] = _DEFAULT_RELEARNING_STEPS
    new_per_day: int = 20
    day_start_hour: int = 4
    learn_ahead_minutes: int = 20


def _warn_config(message: str) -> None:
    warnings.warn(f"invalid scheduler config: {message}", UserWarning, stacklevel=3)


def _duration(value: object) -> timedelta:
    if not isinstance(value, str):
        raise ValueError("duration must be a string such as '10m'")
    match = _DURATION.fullmatch(value)
    if match is None:
        raise ValueError("duration must be a positive number followed by s, m, h, or d")
    amount = int(match[1])
    unit = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}[match[2]]
    try:
        return timedelta(**{unit: amount})
    except OverflowError as exc:
        raise ValueError("duration is too large") from exc


def _parameters(value: object) -> tuple[float, ...]:
    if not isinstance(value, list) or any(
        isinstance(item, bool) or not isinstance(item, (int, float)) for item in value
    ):
        raise ValueError("parameters must be a list of numbers")
    result = tuple(float(item) for item in value)
    if any(not math.isfinite(item) for item in result):
        raise ValueError("parameters must contain only finite numbers")
    try:
        FsrsScheduler(parameters=result)
    except (TypeError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    return result


def load_config(root: str | Path) -> SchedulerConfig:
    """Load scheduler settings from *root* and warn for invalid options."""
    path = Path(root) / ".recall" / "config.toml"
    if not path.exists():
        return SchedulerConfig()
    try:
        with path.open("rb") as file:
            values = tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        _warn_config(f"could not read {path}: {exc}")
        return SchedulerConfig()
    if not isinstance(values, dict):
        _warn_config("top-level value must be a table")
        return SchedulerConfig()

    for key in values:
        if key not in _CONFIG_KEYS:
            _warn_config(f"unknown key {key!r}")

    defaults = SchedulerConfig()

    raw = values.get("desired_retention", defaults.desired_retention)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not 0 < raw < 1:
        _warn_config("desired_retention must be between 0 and 1")
        desired_retention = defaults.desired_retention
    else:
        desired_retention = float(raw)

    if "parameters" in values:
        try:
            parameters = _parameters(values["parameters"])
        except ValueError as exc:
            _warn_config(f"parameters: {exc}")
            parameters = defaults.parameters
    else:
        parameters = defaults.parameters

    parsed_steps: dict[str, tuple[timedelta, ...]] = {}
    for key, default in (
        ("learning_steps", defaults.learning_steps),
        ("relearning_steps", defaults.relearning_steps),
    ):
        if key not in values:
            parsed_steps[key] = default
            continue
        try:
            raw_steps = values[key]
            if not isinstance(raw_steps, list):
                raise ValueError("must be a list of durations")
            parsed_steps[key] = tuple(_duration(item) for item in raw_steps)
        except ValueError as exc:
            _warn_config(f"{key}: {exc}")
            parsed_steps[key] = default

    integer_values: dict[str, int] = {}
    for key, default, valid in (
        (
            "new_per_day",
            defaults.new_per_day,
            lambda value: type(value) is int and value >= 0,
        ),
        (
            "day_start_hour",
            defaults.day_start_hour,
            lambda value: type(value) is int and 0 <= value <= 23,
        ),
        (
            "learn_ahead_minutes",
            defaults.learn_ahead_minutes,
            lambda value: type(value) is int and value >= 0,
        ),
    ):
        raw_value = values.get(key, default)
        if not valid(raw_value):
            _warn_config(f"{key} has an invalid value")
            raw_value = default
        integer_values[key] = raw_value

    return SchedulerConfig(
        desired_retention=desired_retention,
        parameters=parameters,
        learning_steps=parsed_steps["learning_steps"],
        relearning_steps=parsed_steps["relearning_steps"],
        new_per_day=integer_values["new_per_day"],
        day_start_hour=integer_values["day_start_hour"],
        learn_ahead_minutes=integer_values["learn_ahead_minutes"],
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(UTC)


def _local_timezone(now: datetime):
    timezone_name = os.environ.get("TZ", "").lstrip(":")
    if timezone_name:
        try:
            return ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            pass
    return now.astimezone().tzinfo


def _day_bounds(now: datetime, day_start_hour: int) -> tuple[datetime, datetime]:
    timezone = _local_timezone(now)
    local_now = now.astimezone(timezone)
    start_date = local_now.date()
    start_time = time(hour=day_start_hour)
    if local_now.time() < start_time:
        start_date -= timedelta(days=1)
    start = datetime.combine(start_date, start_time, tzinfo=timezone)
    end = datetime.combine(
        start_date + timedelta(days=1),
        start_time,
        tzinfo=timezone,
    )
    return start.astimezone(UTC), end.astimezone(UTC)


def _card_sort_key(card: Card) -> tuple[str, int, str]:
    return (card.file.as_posix(), card.line, card.id or "")


class Scheduler:
    """Keep in-memory FSRS state and select the next card to review."""

    def __init__(
        self,
        parse_result: ParseResult | None = None,
        reviews: Iterable[Review] | ReviewLog | None = None,
        *,
        log: ReviewLog | None = None,
        config: SchedulerConfig | None = None,
    ) -> None:
        if isinstance(reviews, ReviewLog):
            log = reviews
            reviews = None
        self.log = log
        self.config = config or SchedulerConfig()
        self._fsrs = self._make_fsrs()
        self._parse_result: ParseResult | None = None
        self._cards: list[Card] = []
        self._cards_by_id: dict[str, Card] = {}
        self._reviews: list[Review] = []
        self._reviews_by_card: dict[str, list[Review]] = {}
        self._states: dict[str, FsrsCard] = {}
        if parse_result is not None:
            if reviews is None:
                reviews = log.read() if log is not None else ()
            self.reload(parse_result, reviews)

    def _make_fsrs(self) -> FsrsScheduler:
        if self.config.parameters is None:
            return FsrsScheduler(
                desired_retention=self.config.desired_retention,
                learning_steps=self.config.learning_steps,
                relearning_steps=self.config.relearning_steps,
                enable_fuzzing=True,
            )
        return FsrsScheduler(
            parameters=self.config.parameters,
            desired_retention=self.config.desired_retention,
            learning_steps=self.config.learning_steps,
            relearning_steps=self.config.relearning_steps,
            enable_fuzzing=True,
        )

    @staticmethod
    def _fsrs_id(card_id: str) -> int:
        return int.from_bytes(hashlib.sha256(card_id.encode("utf-8")).digest()[:8], "big")

    def _new_state(self, card_id: str, at: datetime) -> FsrsCard:
        return FsrsCard(card_id=self._fsrs_id(card_id), due=at)

    def _replay_card(self, card_id: str, reviews: Iterable[Review]) -> FsrsCard | None:
        state: FsrsCard | None = None
        for review in sorted(reviews, key=lambda item: item.t):
            review_time = _utc(review.t)
            if state is None:
                state = self._new_state(card_id, review_time)
            random.seed(f"{card_id}|{review_time.isoformat()}")
            state, _ = self._fsrs.review_card(
                state,
                FsrsRating(review.rating),
                review_datetime=review_time,
                review_duration=review.ms,
            )
        return state

    def reload(
        self,
        parse_result: ParseResult,
        reviews: Iterable[Review] | None = None,
    ) -> None:
        """Replace parsed cards and replay the supplied review history."""
        if reviews is None:
            reviews = self.log.read() if self.log is not None else ()
        self._parse_result = parse_result
        self._cards = list(parse_result.cards)
        self._cards_by_id = {card.id: card for card in self._cards if card.id is not None}
        self._reviews = list(reviews)
        self._reviews_by_card = {card_id: [] for card_id in self._cards_by_id}
        for review in self._reviews:
            if review.card in self._reviews_by_card:
                self._reviews_by_card[review.card].append(review)
        self._states = {
            card_id: state
            for card_id, card_reviews in self._reviews_by_card.items()
            if (state := self._replay_card(card_id, card_reviews)) is not None
        }

    def card_state(self, card_id: str) -> FsrsCard | None:
        """Return the current FSRS state for a known card, if it has reviews."""
        return self._states.get(card_id)

    def _in_scope(self, card: Card, scope: str | Path | None) -> bool:
        if scope is None:
            return True
        value = Path(scope).as_posix().strip("/")
        if value in {"", "all", "*"}:
            return True
        return card.deck == value or card.deck.startswith(f"{value}/")

    def _queue_parts(
        self,
        scope: str | Path | None,
        now: datetime,
    ) -> tuple[list[Card], list[Card], list[Card], list[Card]]:
        now_utc = _utc(now)
        day_start, day_end = _day_bounds(now, self.config.day_start_hour)
        today_reviews = {review.card for review in self._reviews if day_start <= _utc(review.t) <= now_utc < day_end}
        reviewed_siblings = {
            card.sibling_key for card in self._cards if card.id in today_reviews and card.sibling_key is not None
        }

        def buried(card: Card) -> bool:
            return (
                card.id not in today_reviews and card.sibling_key is not None and card.sibling_key in reviewed_siblings
            )

        learning: list[Card] = []
        review: list[Card] = []
        new: list[Card] = []
        future_learning: list[Card] = []
        learning_cutoff = now_utc + timedelta(minutes=self.config.learn_ahead_minutes)
        for card in self._cards:
            if card.id is None or card.hidden or not self._in_scope(card, scope):
                continue
            state = self._states.get(card.id)
            if state is None:
                if not buried(card):
                    new.append(card)
                continue
            if state.state in (FsrsState.Learning, FsrsState.Relearning):
                if state.due <= now_utc:
                    learning.append(card)
                elif state.due <= learning_cutoff:
                    future_learning.append(card)
            elif state.state == FsrsState.Review and state.due < day_end and not buried(card):
                review.append(card)

        first_reviews = {
            card_id: min(card_reviews, key=lambda item: item.t)
            for card_id, card_reviews in self._reviews_by_card.items()
            if card_reviews
        }
        introduced_today = {
            card_id
            for card_id, first_review in first_reviews.items()
            if day_start <= _utc(first_review.t) <= now_utc < day_end
        }
        available = max(0, self.config.new_per_day - len(introduced_today))
        new = new[:available]

        def due_key(card: Card) -> tuple[datetime, str, int, str]:
            assert card.id is not None
            return (self._states[card.id].due, *_card_sort_key(card))

        learning.sort(key=due_key)
        future_learning.sort(key=due_key)
        review.sort(key=due_key)
        new.sort(key=_card_sort_key)
        return learning, review, new, future_learning

    def next_card(self, scope: str | Path | None, now: datetime) -> Card | None:
        """Return the next card for *scope*, or ``None`` when its queue is empty."""
        learning, review, new, future_learning = self._queue_parts(scope, now)
        if learning:
            return learning[0]
        if review:
            return review[0]
        if new:
            return new[0]
        return future_learning[0] if future_learning else None

    def counts(self, scope: str | Path | None, now: datetime) -> tuple[int, int]:
        """Return the number of due and available new cards in *scope*."""
        learning, review, new, _ = self._queue_parts(scope, now)
        return len(learning) + len(review), len(new)

    def record(self, card_id: str, rating: int, ms: int, now: datetime) -> Card:
        """Append a review and update the reviewed card's in-memory state."""
        if card_id not in self._cards_by_id:
            raise ValueError(f"unknown card ID: {card_id}")
        if self.log is None:
            raise RuntimeError("record requires a ReviewLog")
        review_time = _utc(now).replace(microsecond=0)
        self.log.append(card_id, review_time, rating, ms)
        review = Review(card=card_id, t=review_time, rating=rating, ms=ms)
        self._reviews.append(review)
        self._reviews_by_card[card_id].append(review)
        state = self._replay_card(card_id, self._reviews_by_card[card_id])
        assert state is not None
        self._states[card_id] = state
        return self._cards_by_id[card_id]

    def undo(self) -> Review | None:
        """Undo the last uncommitted review and replay the affected card."""
        if self.log is None:
            return None
        removed = self.log.undo_last()
        if removed is None:
            return None

        for index in range(len(self._reviews) - 1, -1, -1):
            if self._reviews[index] == removed:
                del self._reviews[index]
                break
        card_reviews = self._reviews_by_card.get(removed.card)
        if card_reviews is not None:
            for index in range(len(card_reviews) - 1, -1, -1):
                if card_reviews[index] == removed:
                    del card_reviews[index]
                    break
            state = self._replay_card(removed.card, card_reviews)
            if state is None:
                self._states.pop(removed.card, None)
            else:
                self._states[removed.card] = state
        return removed


Config = SchedulerConfig
load_scheduler_config = load_config

__all__ = [
    "Config",
    "Scheduler",
    "SchedulerConfig",
    "load_config",
    "load_scheduler_config",
]
