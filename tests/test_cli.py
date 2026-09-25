"""Tests for the recall command-line interface."""

from pathlib import Path

import pytest

from recall.cli import main


def test_help_lists_commands(capsys: pytest.CaptureFixture[str]) -> None:
    """The top-level help lists the commands available to users."""
    with pytest.raises(SystemExit) as error:
        main(["--help"])

    assert error.value.code == 0
    output = capsys.readouterr().out
    assert "serve" in output
    assert "check" in output


def test_serve_is_not_implemented_yet(capsys: pytest.CaptureFixture[str]) -> None:
    """The web app remains outside the scope of the check command."""
    assert main(["serve"]) == 1
    assert capsys.readouterr().out == "not implemented\n"


def test_check_clean_repo_uses_the_current_directory_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "Deck.md").write_text("Question\n?\nAnswer\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert main(["check"]) == 0
    assert capsys.readouterr().out == "1 decks, 1 cards, 0 problems\n"


def test_check_reports_filesystem_math_and_duplicate_problems(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "Deck.md").write_text(
        "Question\n?\nAnswer\n![missing](missing.png)\n\nUnclosed $math\n",
        encoding="utf-8",
    )
    (tmp_path / "Other.md").write_text("Question\n?\nAnswer\n", encoding="utf-8")
    outside = tmp_path.parent / "outside.png"
    outside.write_bytes(b"image")
    (tmp_path / "Nested.md").write_text(
        "![outside](../outside.png)\n", encoding="utf-8"
    )

    assert main(["check", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert "Deck.md:4: missing image: 'missing.png'" in output
    assert "Deck.md:6: unclosed math delimiter '$'" in output
    assert "Nested.md:1: image path escapes repository: '../outside.png'" in output
    assert "duplicate card ID" in output
    assert output.endswith("0 decks, 0 cards, 4 problems\n")


def test_check_reports_reference_image_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "Deck.md").write_text(
        "text\n![first][a]\n![second](missing.png)\n\n[a]: missing.png\n",
        encoding="utf-8",
    )

    assert main(["check", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert "Deck.md:2: missing image: 'missing.png'" in output
    assert "Deck.md:3: missing image: 'missing.png'" in output
    assert output.endswith("0 decks, 0 cards, 2 problems\n")


def test_check_does_not_pair_math_across_markdown_blocks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "Deck.md").write_text(
        "First $x\n\n---\n\nSecond $y\n", encoding="utf-8"
    )

    assert main(["check", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert "Deck.md:1: unclosed math delimiter '$'" in output
    assert "Deck.md:5: unclosed math delimiter '$'" in output
    assert output.endswith("0 decks, 0 cards, 2 problems\n")
