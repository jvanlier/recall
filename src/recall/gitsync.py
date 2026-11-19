"""Pull card edits into the cards repository with git."""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

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
    """The outcome of one pull attempt."""

    head_changed: bool = False
    error: str | None = None
    warnings: tuple[str, ...] = ()

    @property
    def successful(self) -> bool:
        """Whether the pull completed without a git error."""
        return self.error is None


class GitSync:
    """Fast-forward the cards repository to its upstream branch.

    The app never writes to the cards repository, so a fast-forward pull is
    all that is needed. The lock keeps two triggers from running git at once.
    """

    def __init__(self, root: str | Path, *, timeout: float = 15.0) -> None:
        self.root = Path(root).expanduser()
        if timeout <= 0:
            raise ValueError("git timeout must be positive")
        self.timeout = timeout
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

    def sync(self) -> SyncResult:
        """Run one serialised ``git pull --ff-only``."""
        with self._lock:
            try:
                initial_head = self._head()
                self._run("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
            except GitCommandError as error:
                return SyncResult(warnings=(f"no upstream branch to pull from ({error.message})",))
            try:
                self._run("pull", "--ff-only")
                return SyncResult(head_changed=initial_head != self._head())
            except GitCommandError as error:
                _LOGGER.warning("git pull failed: %s", error)
                return SyncResult(error=str(error))


__all__ = ["GitCommandError", "GitSync", "SyncResult"]
