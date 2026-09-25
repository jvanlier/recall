"""Command-line interface for recall."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from recall.check import check_repo


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="recall",
        description="Review markdown cards with spaced repetition.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("serve", help="run the review web app")
    check = subparsers.add_parser("check", help="check a cards repository")
    check.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=None,
        help="cards repository to check (default: current directory)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the recall command-line interface."""
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        print("not implemented")
        return 1

    try:
        result = check_repo(Path.cwd() if args.path is None else args.path)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"recall check: {error}")
        return 1

    for warning in result.warnings:
        print(f"{warning.file}:{warning.line}: {warning.message}")
    print(
        f"{len(result.decks)} decks, {len(result.cards)} cards, "
        f"{len(result.warnings)} problems"
    )
    return int(bool(result.warnings))
