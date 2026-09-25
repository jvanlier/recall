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
    """The web app command remains a placeholder until the web app ticket."""
    assert main(["serve"]) == 1
    assert capsys.readouterr().out == "not implemented\n"


def test_check_clean_repo_returns_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "Deck.md").write_text("Question\n?\nAnswer\n", encoding="utf-8")

    assert main(["check", str(tmp_path)]) == 0

    assert capsys.readouterr().out == "1 decks, 1 cards, 0 problems\n"


def test_check_reports_problems_and_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "present.png").write_bytes(b"image")
    (tmp_path / "Deck.md").write_text(
        """Question
?
![present](images/present.png)
![not an image]
![missing](images/missing.png)
![escape](../outside.png)
An unclosed $formula
""",
        encoding="utf-8",
    )
    (tmp_path / "Duplicate.md").write_text(
        "Question\n?\nAnother answer\n", encoding="utf-8"
    )

    assert main(["check", str(tmp_path)]) == 1

    output = capsys.readouterr().out
    assert "Deck.md:5: missing image: 'images/missing.png'" in output
    assert "Deck.md:6: image path escapes repository: '../outside.png'" in output
    assert "Deck.md:7: unclosed math delimiter '$'" in output
    assert "Deck.md:2: duplicate card ID" in output
    assert output.endswith("0 decks, 0 cards, 4 problems\n")


def test_check_respects_code_and_math_precedence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "Deck.md").write_text(
        """Question
?
$x`y$ and `code`
$x \\text{<!-- marker -->} y$
""",
        encoding="utf-8",
    )

    assert main(["check", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "1 decks, 1 cards, 0 problems\n"


def test_check_uses_current_directory_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "Deck.md").write_text("Question\n?\nAnswer\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert main(["check"]) == 0
    assert capsys.readouterr().out == "1 decks, 1 cards, 0 problems\n"
