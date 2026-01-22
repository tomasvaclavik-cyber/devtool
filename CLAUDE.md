# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Development Commands

```bash
# Install dependencies (use virtual environment)
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run the CLI
ote --help
ote spot                  # aktuální spotová cena
ote spot --all            # všechny 15min intervaly
ote spot -d 2026-01-21    # data pro konkrétní den

# Run tests
pytest                    # all tests
pytest tests/test_cli.py  # specific file
pytest -k "test_version"  # specific test by name

# Linting & formatting
ruff check src tests
ruff check --fix src tests
ruff format src tests

# Type checking
mypy src
```

## Architecture

- **src/ote/cli.py** - Main CLI entry point using Click. Commands defined as `@main.command()`.
- **src/ote/spot.py** - OTE API client for fetching spot prices, CNB exchange rate.
- **src/ote/__init__.py** - Package init, contains version string.
- **tests/** - pytest tests using Click's CliRunner.

## Data Sources

- **OTE** (ote-cr.cz) - Czech electricity market operator, provides 15-minute spot prices
- **ČNB** (cnb.cz) - Czech National Bank, provides EUR/CZK exchange rate
