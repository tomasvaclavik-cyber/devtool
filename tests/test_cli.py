"""Testy pro CLI."""

from click.testing import CliRunner

from devtool.cli import main


def test_version() -> None:
    """Test zobrazení verze."""
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_init_command() -> None:
    """Test příkazu init."""
    runner = CliRunner()
    result = runner.invoke(main, ["init", "test-projekt"])
    assert result.exit_code == 0
    assert "test-projekt" in result.output


def test_lint_command() -> None:
    """Test příkazu lint."""
    runner = CliRunner()
    result = runner.invoke(main, ["lint"])
    assert result.exit_code == 0


def test_build_command() -> None:
    """Test příkazu build."""
    runner = CliRunner()
    result = runner.invoke(main, ["build"])
    assert result.exit_code == 0
