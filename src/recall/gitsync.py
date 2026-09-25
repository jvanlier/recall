"""Synchronise the cards repository with git."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from recall.log import Review, ReviewLog
from recall.parser import load_repo

_REVIEW_ATTRIBUTE = re.compile(r"^\s*\.recall/reviews\.jsonl\s+merge=union(?:\s|$)")
_LOGGER = logging.getLogger(__name__)


class GitCommandError(RuntimeError):
    """A git command failed or exceeded its timeout."""

    def __init__(self, command: Iterable[str], message: str, *, returncode: int | None = None) -> None:
        self.command = tuple(command)
        self.returncode = returncode
        self.message = message
        super().__init__(f"git {' '.join(self.command)}: {message}")


@dataclass(frozen=True, slots=True)
class SyncResult:
    """The outcome of one synchronisation attempt."""

    committed: bool = False
    pushed: bool = False
    head_changed: bool = False
    error: str | None = None
    warnings: tuple[str, ...] = ()

    @property
    def successful(self) -> bool:
        """Whether the sync completed without a git error."""
        return self.error is None


class GitSync:
    """Commit review records, rebase card edits, and push the repository.

    All subprocesses run with ``cwd`` set to the cards repository.  The lock is
    deliberately around the complete operation: a second trigger must not run
    git while a rebase or push from the first trigger is still in progress.
    """

    def __init__(
        self,
        root: str | Path,
        log: ReviewLog,
        *,
        timeout: float = 15.0,
        card_decks: Mapping[str, str] | None = None,
    ) -> None:
        self.root = Path(root).expanduser()
        self.log = log
        if timeout <= 0:
            raise ValueError("git timeout must be positive")
        self.timeout = timeout
        self.card_decks = dict(card_decks or {})
        self._lock = threading.Lock()

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        command = ("git", *args)
        try:
            environment = os.environ.copy()
            environment["GIT_TERMINAL_PROMPT"] = "0"
            result = subprocess.run(
                command,
                cwd=self.root,
                capture_output=True,
                check=False,
                env=environment,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as error:
            raise GitCommandError(args, f"timed out after {self.timeout:g}s") from error
        except OSError as error:
            raise GitCommandError(args, str(error)) from error
        if result.returncode:
            details = (result.stderr or result.stdout).strip()
            raise GitCommandError(args, details or "command failed", returncode=result.returncode)
        return result

    def _head(self) -> str:
        return self._run("rev-parse", "--verify", "HEAD").stdout.strip()

    def _warnings(self) -> list[str]:
        path = self.root / ".gitattributes"
        try:
            attributes = path.read_text(encoding="utf-8")
        except OSError:
            attributes = ""
        if any(_REVIEW_ATTRIBUTE.match(line) for line in attributes.splitlines()):
            return []
        return [".gitattributes lacks .recall/reviews.jsonl merge=union"]

    def _upstream(self) -> str | None:
        try:
            return self._run("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}").stdout.strip()
        except GitCommandError:
            return None

    def _review_change_count(self) -> int:
        """Count appended log lines left dirty by an earlier process."""
        status = self._run("status", "--porcelain", "--", ".recall/reviews.jsonl").stdout
        if not status:
            return 0
        try:
            diff = self._run("diff", "--numstat", "HEAD", "--", ".recall/reviews.jsonl").stdout.splitlines()
            added = sum(int(line.split()[0]) for line in diff if line.split())
        except GitCommandError, ValueError:
            added = 0
        return added or len(self.log.read())

    def _decks_for(self, reviews: Iterable[Review]) -> list[str]:
        mapping = self.card_decks
        if not mapping:
            try:
                mapping = {card.id: card.deck for card in load_repo(self.root).cards if card.id}
            except OSError, RuntimeError, ValueError:
                mapping = {}
        decks: set[str] = set()
        for review in reviews:
            decks.add(mapping.get(review.card, "unknown"))
        return sorted(decks, key=str.casefold)

    def _commit_message(self, reviews: list[Review], count: int | None = None) -> str:
        amount = len(reviews) if count is None else count
        decks = self._decks_for(reviews)
        return f"reviews: {amount} cards ({', '.join(decks) or 'unknown'})"

    def sync(self) -> SyncResult:
        """Run one serialised commit, pull, and push operation."""
        with self._lock:
            warnings = self._warnings()
            try:
                initial_head = self._head()
            except GitCommandError as error:
                _LOGGER.warning("git sync failed: %s", error)
                return SyncResult(error=str(error), warnings=tuple(warnings))

            pending_reviews = self.log.pending_reviews()
            pending_count = len(pending_reviews)
            if not pending_reviews:
                try:
                    dirty_count = self._review_change_count()
                except GitCommandError as error:
                    _LOGGER.warning("git sync failed: %s", error)
                    return SyncResult(error=str(error), warnings=tuple(warnings))
                if dirty_count:
                    all_reviews = self.log.read()
                    pending_reviews = all_reviews[-dirty_count:]

            committed = False
            if pending_reviews:
                try:
                    self._run("add", "--", ".recall/reviews.jsonl")
                    self._run(
                        "commit",
                        "-m",
                        self._commit_message(pending_reviews),
                    )
                except GitCommandError as error:
                    _LOGGER.warning("git sync failed: %s", error)
                    return SyncResult(error=str(error), warnings=tuple(warnings))
                if pending_count:
                    self.log.mark_committed(pending_count)
                committed = True

            upstream = self._upstream()
            if upstream is None:
                warnings.append("repository has no upstream branch")
                return SyncResult(
                    committed=committed,
                    head_changed=initial_head != self._head(),
                    warnings=tuple(warnings),
                )

            try:
                self._run("pull", "--rebase")
            except GitCommandError as error:
                _LOGGER.warning("git sync failed: %s", error)
                try:
                    self._run("rebase", "--abort")
                except GitCommandError:
                    pass
                return SyncResult(
                    committed=committed,
                    head_changed=initial_head != self._head(),
                    error=str(error),
                    warnings=tuple(warnings),
                )

            try:
                ahead = int(self._run("rev-list", "--count", "@{u}..HEAD").stdout.strip())
            except (GitCommandError, ValueError) as error:
                _LOGGER.warning("git sync failed: %s", error)
                if isinstance(error, GitCommandError):
                    message = str(error)
                else:
                    message = f"git rev-list returned a non-integer count: {error}"
                return SyncResult(
                    committed=committed,
                    head_changed=initial_head != self._head(),
                    error=message,
                    warnings=tuple(warnings),
                )

            pushed = False
            if ahead:
                try:
                    self._run("push")
                except GitCommandError as error:
                    _LOGGER.warning("git sync failed: %s", error)
                    return SyncResult(
                        committed=committed,
                        head_changed=initial_head != self._head(),
                        error=str(error),
                        warnings=tuple(warnings),
                    )
                pushed = True

            return SyncResult(
                committed=committed,
                pushed=pushed,
                head_changed=initial_head != self._head(),
                warnings=tuple(warnings),
            )


def sync(
    root: str | Path,
    log: ReviewLog,
    *,
    timeout: float = 15.0,
    card_decks: Mapping[str, str] | None = None,
) -> SyncResult:
    """Synchronise a cards repository once."""
    return GitSync(root, log, timeout=timeout, card_decks=card_decks).sync()


__all__ = ["GitCommandError", "GitSync", "SyncResult", "sync"]
