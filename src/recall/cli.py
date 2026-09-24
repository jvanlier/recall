"""Command-line interface for recall."""

from __future__ import annotations

import argparse
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="recall",
        description="Review markdown cards with spaced repetition.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("serve", help="run the review web app")
    subparsers.add_parser("check", help="check a cards repository")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the recall command-line interface."""
    args = build_parser().parse_args(argv)
    del args
    print("not implemented")
    return 1
