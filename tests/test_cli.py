"""Testy pro CLI."""

from click.testing import CliRunner

from ote.cli import main


def test_version() -> None:
    """Test zobrazení verze."""
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "0.2.0" in result.output


def test_spot_command() -> None:
    """Test příkazu spot."""
    runner = CliRunner()
    result = runner.invoke(main, ["spot"])
    assert result.exit_code == 0
    assert "CZK" in result.output or "Načítám" in result.output
