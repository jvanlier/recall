"""Tests for the recall command-line interface."""

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


@pytest.mark.parametrize("command", ["serve", "check"])
def test_commands_are_not_implemented_yet(
    command: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """The placeholder commands have the documented result for now."""
    assert main([command]) == 1
    assert capsys.readouterr().out == "not implemented\n"
