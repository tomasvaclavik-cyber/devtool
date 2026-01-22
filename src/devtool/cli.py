"""Hlavní CLI rozhraní."""

from datetime import date

import click
from rich.console import Console
from rich.table import Table

from devtool import __version__
from devtool.ote import fetch_spot_prices, get_current_price

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


@main.command()
@click.option("--date", "-d", "report_date", default=None, help="Datum (YYYY-MM-DD), výchozí dnes")
@click.option("--all", "-a", "show_all", is_flag=True, help="Zobrazit všechny hodiny")
def ote(report_date: str | None, show_all: bool) -> None:
    """Zobrazí spotové ceny elektřiny z OTE."""
    try:
        if report_date:
            dt = date.fromisoformat(report_date)
        else:
            dt = date.today()

        console.print(f"[cyan]Načítám spotové ceny pro {dt}...[/cyan]")
        prices = fetch_spot_prices(dt)

        if not prices:
            console.print("[red]Žádná data nejsou k dispozici.[/red]")
            return

        current = get_current_price(prices)

        if current and not show_all:
            console.print()
            console.print(f"[bold green]Aktuální cena ({current.time_from.strftime('%H:%M')} - {current.time_to.strftime('%H:%M')}):[/bold green]")
            console.print(f"[bold yellow]{current.price_eur:.2f} EUR/MWh[/bold yellow]")
            console.print()

        if show_all or not current:
            table = Table(title=f"Spotové ceny OTE - {dt}")
            table.add_column("Hodina", style="cyan")
            table.add_column("Cena (EUR/MWh)", justify="right", style="yellow")

            for price in prices:
                hour_str = f"{price.time_from.strftime('%H:%M')} - {price.time_to.strftime('%H:%M')}"
                is_current = current and price.time_from == current.time_from
                if is_current:
                    table.add_row(f"[bold]{hour_str}[/bold]", f"[bold]{price.price_eur:.2f}[/bold]")
                else:
                    table.add_row(hour_str, f"{price.price_eur:.2f}")

            console.print(table)

    except Exception as e:
        console.print(f"[red]Chyba: {e}[/red]")


if __name__ == "__main__":
    main()
