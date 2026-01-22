"""Hlavní CLI rozhraní."""

from datetime import date

import click
from rich.console import Console
from rich.table import Table

from ote import __version__
from ote.spot import fetch_spot_prices, get_current_price

console = Console()


@click.group()
@click.version_option(version=__version__)
def main() -> None:
    """OTE - Spotové ceny elektřiny z OTE."""
    pass


@main.command()
@click.option("--date", "-d", "report_date", default=None, help="Datum (YYYY-MM-DD), výchozí dnes")
@click.option("--all", "-a", "show_all", is_flag=True, help="Zobrazit všechny 15min intervaly")
def spot(report_date: str | None, show_all: bool) -> None:
    """Zobrazí spotové ceny elektřiny z OTE v CZK."""
    try:
        if report_date:
            dt = date.fromisoformat(report_date)
        else:
            dt = date.today()

        console.print(f"[cyan]Načítám spotové ceny pro {dt}...[/cyan]")
        prices, eur_czk_rate = fetch_spot_prices(dt)

        if not prices:
            console.print("[red]Žádná data nejsou k dispozici.[/red]")
            return

        console.print(f"[dim]Kurz ČNB: 1 EUR = {eur_czk_rate:.3f} CZK[/dim]")

        current = get_current_price(prices)

        if current and not show_all:
            console.print()
            time_range = f"{current.time_from:%H:%M} - {current.time_to:%H:%M}"
            console.print(f"[bold green]Aktuální cena ({time_range}):[/bold green]")
            console.print(f"[bold yellow]{current.price_czk:.2f} CZK/MWh[/bold yellow]")
            console.print()

        if show_all or not current:
            table = Table(title=f"Spotové ceny OTE - {dt}")
            table.add_column("Hodina", style="cyan")
            table.add_column("Cena (CZK/MWh)", justify="right", style="yellow")

            for price in prices:
                hour_str = f"{price.time_from:%H:%M} - {price.time_to:%H:%M}"
                is_current = current and price.time_from == current.time_from
                if is_current:
                    table.add_row(f"[bold]{hour_str}[/bold]", f"[bold]{price.price_czk:.2f}[/bold]")
                else:
                    table.add_row(hour_str, f"{price.price_czk:.2f}")

            console.print(table)

    except Exception as e:
        console.print(f"[red]Chyba: {e}[/red]")


if __name__ == "__main__":
    main()
