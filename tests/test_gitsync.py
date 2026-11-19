"""Tests for pulling card edits into the cards repository."""

import subprocess
from pathlib import Path

from recall.gitsync import GitSync


def git(*args: str, cwd: Path) -> str:
    result = subprocess.run(("git", *args), cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def clone_with_edit_upstream(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    git("init", "--bare", str(remote), cwd=tmp_path)
    laptop = tmp_path / "laptop"
    git("clone", str(remote), str(laptop), cwd=tmp_path)
    git("config", "user.name", "Test", cwd=laptop)
    git("config", "user.email", "test@example.com", cwd=laptop)
    (laptop / "Deck.md").write_text("Question::Answer\n", encoding="utf-8")
    git("add", ".", cwd=laptop)
    git("commit", "-m", "cards", cwd=laptop)
    git("branch", "-M", "main", cwd=laptop)
    git("push", "-u", "origin", "main", cwd=laptop)
    cards = tmp_path / "cards"
    git("clone", "--branch", "main", str(remote), str(cards), cwd=tmp_path)
    return cards, laptop


def test_sync_pulls_card_edits(tmp_path: Path) -> None:
    cards, laptop = clone_with_edit_upstream(tmp_path)
    (laptop / "Deck.md").write_text("Question::Updated\n", encoding="utf-8")
    git("commit", "-am", "update card", cwd=laptop)
    git("push", cwd=laptop)

    result = GitSync(cards).sync()

    assert result.successful
    assert result.head_changed is True
    assert (cards / "Deck.md").read_text(encoding="utf-8") == "Question::Updated\n"
    assert GitSync(cards).sync() == type(result)()


def test_diverged_clone_reports_an_error(tmp_path: Path) -> None:
    cards, laptop = clone_with_edit_upstream(tmp_path)
    (laptop / "Deck.md").write_text("Question::Laptop\n", encoding="utf-8")
    git("commit", "-am", "laptop", cwd=laptop)
    git("push", cwd=laptop)
    git("config", "user.name", "Test", cwd=cards)
    git("config", "user.email", "test@example.com", cwd=cards)
    (cards / "Deck.md").write_text("Question::Server\n", encoding="utf-8")
    git("commit", "-am", "server", cwd=cards)

    result = GitSync(cards).sync()

    assert result.error is not None
    assert (cards / "Deck.md").read_text(encoding="utf-8") == "Question::Server\n"


def test_sync_warns_without_upstream(tmp_path: Path) -> None:
    cards = tmp_path / "cards"
    git("init", str(cards), cwd=tmp_path)

    result = GitSync(cards).sync()

    assert result.successful
    assert result.warnings and "no upstream branch" in result.warnings[0]
