"""Hlavní CLI rozhraní."""

import click
from rich.console import Console

from devtool import __version__

console = Console()


@click.group()
@click.version_option(version=__version__)
def main() -> None:
    """DevTool - CLI nástroj pro automatizaci vývoje."""
    pass


@main.command()
@click.argument("name")
def init(name: str) -> None:
    """Inicializuje nový projekt s daným názvem."""
    console.print(f"[green]Inicializuji projekt:[/green] {name}")


@main.command()
@click.option("--fix", is_flag=True, help="Automaticky opravit problémy")
def lint(fix: bool) -> None:
    """Spustí linting na zdrojovém kódu."""
    if fix:
        console.print("[yellow]Spouštím linting s opravami...[/yellow]")
    else:
        console.print("[blue]Spouštím linting...[/blue]")


@main.command()
def build() -> None:
    """Sestaví projekt."""
    console.print("[cyan]Sestavuji projekt...[/cyan]")


if __name__ == "__main__":
    main()
