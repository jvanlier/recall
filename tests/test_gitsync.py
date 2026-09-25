"""Tests for cards-repository synchronisation."""

import subprocess
from datetime import UTC, datetime
from pathlib import Path

from recall.gitsync import GitSync
from recall.log import ReviewLog
from recall.parser import load_repo


def git(*args: str, cwd: Path) -> str:
    result = subprocess.run(("git", *args), cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def cards_repo(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    git("init", "--bare", str(remote), cwd=tmp_path)
    cards = tmp_path / "cards"
    git("clone", str(remote), str(cards), cwd=tmp_path)
    git("config", "user.name", "Test", cwd=cards)
    git("config", "user.email", "test@example.com", cwd=cards)
    (cards / ".gitattributes").write_text(".recall/reviews.jsonl merge=union\n", encoding="utf-8")
    (cards / "Deck.md").write_text("Question::Answer\n", encoding="utf-8")
    git("add", ".", cwd=cards)
    git("commit", "-m", "cards", cwd=cards)
    git("branch", "-M", "main", cwd=cards)
    git("push", "-u", "origin", "main", cwd=cards)
    return cards, remote


def test_sync_commits_and_pushes_reviews(tmp_path: Path) -> None:
    cards, _remote = cards_repo(tmp_path)
    card = load_repo(cards).cards[0]
    log = ReviewLog(cards / ".recall" / "reviews.jsonl")
    assert card.id is not None
    log.append(card.id, datetime.now(UTC), 3, 42)

    result = GitSync(cards, log).sync()

    assert result.successful
    assert result.committed is True
    assert result.pushed is True
    assert log.pending == 0
    assert git("log", "-1", "--pretty=%s", cwd=cards) == "reviews: 1 cards (Deck)"


def test_sync_pulls_card_edits_before_pushing(tmp_path: Path) -> None:
    cards, remote = cards_repo(tmp_path)
    other = tmp_path / "other"
    git("clone", "--branch", "main", str(remote), str(other), cwd=tmp_path)
    git("config", "user.name", "Other", cwd=other)
    git("config", "user.email", "other@example.com", cwd=other)
    (other / "Deck.md").write_text("Question::Updated\n", encoding="utf-8")
    git("add", "Deck.md", cwd=other)
    git("commit", "-m", "update card", cwd=other)
    git("push", cwd=other)

    result = GitSync(cards, ReviewLog(cards / ".recall" / "reviews.jsonl")).sync()

    assert result.successful
    assert result.head_changed is True
    assert (cards / "Deck.md").read_text(encoding="utf-8") == "Question::Updated\n"


def test_concurrent_review_appends_merge_and_push(tmp_path: Path) -> None:
    cards, remote = cards_repo(tmp_path)
    other = tmp_path / "other"
    git("clone", "--branch", "main", str(remote), str(other), cwd=tmp_path)
    git("config", "user.name", "Other", cwd=other)
    git("config", "user.email", "other@example.com", cwd=other)
    other_log = ReviewLog(other / ".recall" / "reviews.jsonl")
    other_log.append("other", datetime(2026, 1, 1, tzinfo=UTC), 2, 10)
    git("add", ".recall/reviews.jsonl", cwd=other)
    git("commit", "-m", "other review", cwd=other)
    git("push", cwd=other)

    card = load_repo(cards).cards[0]
    assert card.id is not None
    log = ReviewLog(cards / ".recall" / "reviews.jsonl")
    log.append(card.id, datetime(2026, 1, 2, tzinfo=UTC), 3, 20)

    result = GitSync(cards, log).sync()

    assert result.successful
    assert len(log.read()) == 2
    assert "other" in git("show", "main:.recall/reviews.jsonl", cwd=remote)
    assert card.id in git("show", "main:.recall/reviews.jsonl", cwd=remote)


def test_push_failure_keeps_commit_for_the_next_sync(tmp_path: Path) -> None:
    cards, remote = cards_repo(tmp_path)
    card = load_repo(cards).cards[0]
    log = ReviewLog(cards / ".recall" / "reviews.jsonl")
    assert card.id is not None
    log.append(card.id, datetime.now(UTC), 3, 42)
    hook = remote / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)

    failed = GitSync(cards, log).sync()

    assert failed.committed is True
    assert failed.error is not None
    assert log.pending == 0
    hook.unlink()

    retried = GitSync(cards, log).sync()

    assert retried.successful
    assert retried.pushed is True


def test_sync_warns_about_merge_attribute_and_upstream(tmp_path: Path) -> None:
    cards = tmp_path / "cards"
    git("init", str(cards), cwd=tmp_path)
    git("config", "user.name", "Test", cwd=cards)
    git("config", "user.email", "test@example.com", cwd=cards)
    (cards / "Deck.md").write_text("Question::Answer\n", encoding="utf-8")
    git("add", ".", cwd=cards)
    git("commit", "-m", "cards", cwd=cards)

    result = GitSync(cards, ReviewLog(cards / ".recall" / "reviews.jsonl")).sync()

    assert result.successful
    assert ".gitattributes lacks .recall/reviews.jsonl merge=union" in result.warnings
    assert "repository has no upstream branch" in result.warnings
