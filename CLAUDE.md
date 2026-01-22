# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Development Commands

```bash
# Install dependencies (use virtual environment)
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run the CLI
devtool --help
devtool init <project-name>
devtool lint [--fix]
devtool build

# Run tests
pytest                    # all tests
pytest tests/test_cli.py  # specific file
pytest -k "test_init"     # specific test by name

# Linting & formatting
ruff check src tests      # check for issues
ruff check --fix src tests # auto-fix issues
ruff format src tests     # format code

# Type checking
mypy src
```

## Architecture

- **src/devtool/cli.py** - Main CLI entry point using Click. All commands are defined here as `@main.command()` decorated functions.
- **src/devtool/__init__.py** - Package init, contains version string.
- **tests/** - pytest tests using Click's CliRunner for testing CLI commands.

## CLI Framework

Uses [Click](https://click.palletsprojects.com/) for command-line interface with [Rich](https://rich.readthedocs.io/) for formatted console output. New commands should follow the pattern in `cli.py`:

```python
@main.command()
@click.option("--flag", is_flag=True, help="Description")
def command_name(flag: bool) -> None:
    """Command docstring shown in --help."""
    console.print("[color]message[/color]")
```
