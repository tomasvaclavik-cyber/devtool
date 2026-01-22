"""Hlavní CLI rozhraní."""

from datetime import date

import click
from rich.console import Console
from rich.table import Table

from ote import __version__
from ote.db import (
    get_available_dates,
    get_connection,
    get_daily_stats,
    get_prices_for_date,
    save_prices,
)
from ote.spot import fetch_spot_prices, get_current_price

console = Console()


@click.group()
@click.version_option(version=__version__)
def main() -> None:
    """OTE - Spotové ceny elektřiny z OTE."""
    pass


@main.command()
@click.option(
    "--date", "-d", "report_date", default=None, help="Datum (YYYY-MM-DD), výchozí dnes"
)
@click.option(
    "--all", "-a", "show_all", is_flag=True, help="Zobrazit všechny 15min intervaly"
)
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
                    table.add_row(
                        f"[bold]{hour_str}[/bold]", f"[bold]{price.price_czk:.2f}[/bold]"
                    )
                else:
                    table.add_row(hour_str, f"{price.price_czk:.2f}")

            console.print(table)

    except Exception as e:
        console.print(f"[red]Chyba: {e}[/red]")


@main.command()
@click.option(
    "--date", "-d", "report_date", default=None, help="Datum (YYYY-MM-DD), výchozí dnes"
)
def save(report_date: str | None) -> None:
    """Stáhne a uloží spotové ceny do databáze."""
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

        conn = get_connection()
        count = save_prices(conn, dt, prices, eur_czk_rate)
        conn.close()

        console.print(f"[green]Uloženo {count} záznamů pro {dt}[/green]")
        console.print(f"[dim]Kurz ČNB: 1 EUR = {eur_czk_rate:.3f} CZK[/dim]")

    except Exception as e:
        console.print(f"[red]Chyba: {e}[/red]")


@main.command()
@click.option(
    "--date", "-d", "report_date", default=None, help="Datum (YYYY-MM-DD) pro detail"
)
def history(report_date: str | None) -> None:
    """Zobrazí historická data z databáze."""
    try:
        conn = get_connection()

        if report_date:
            # Zobraz detail pro konkrétní den
            dt = date.fromisoformat(report_date)
            prices = get_prices_for_date(conn, dt)
            stats = get_daily_stats(conn, dt)

            if not prices or not stats:
                console.print(f"[red]Žádná data pro {dt} v databázi.[/red]")
                conn.close()
                return

            console.print(f"[dim]Kurz ČNB: 1 EUR = {stats['eur_czk_rate']:.3f} CZK[/dim]")
            console.print()

            table = Table(title=f"Spotové ceny OTE - {dt} (z databáze)")
            table.add_column("Hodina", style="cyan")
            table.add_column("Cena (CZK/MWh)", justify="right", style="yellow")

            for price in prices:
                hour_str = f"{price.time_from:%H:%M} - {price.time_to:%H:%M}"
                table.add_row(hour_str, f"{price.price_czk:.2f}")

            console.print(table)

            console.print()
            console.print(f"[dim]Min: {stats['min']:.2f} CZK/MWh[/dim]")
            console.print(f"[dim]Max: {stats['max']:.2f} CZK/MWh[/dim]")
            console.print(f"[dim]Průměr: {stats['avg']:.2f} CZK/MWh[/dim]")

        else:
            # Zobraz přehled všech dostupných dnů
            dates = get_available_dates(conn)

            if not dates:
                console.print("[yellow]Databáze je prázdná.[/yellow]")
                console.print("[dim]Použijte 'ote save' pro uložení dat.[/dim]")
                conn.close()
                return

            table = Table(title="Dostupná data v databázi")
            table.add_column("Datum", style="cyan")
            table.add_column("Min (CZK/MWh)", justify="right")
            table.add_column("Max (CZK/MWh)", justify="right")
            table.add_column("Průměr (CZK/MWh)", justify="right", style="yellow")

            for d in dates:
                stats = get_daily_stats(conn, d)
                if stats:
                    table.add_row(
                        str(d),
                        f"{stats['min']:.2f}",
                        f"{stats['max']:.2f}",
                        f"{stats['avg']:.2f}",
                    )

            console.print(table)
            console.print()
            console.print("[dim]Pro detail použijte: ote history -d YYYY-MM-DD[/dim]")

        conn.close()

    except Exception as e:
        console.print(f"[red]Chyba: {e}[/red]")


@main.command()
@click.option("--port", "-p", default=8501, help="Port pro web server")
def dashboard(port: int) -> None:
    """Spustí webový dashboard (vyžaduje: pip install ote[dashboard])."""
    import subprocess
    import sys

    try:
        from ote import dashboard as dash_module  # noqa: F401
    except ImportError:
        console.print("[red]Dashboard není nainstalován.[/red]")
        console.print("[dim]Nainstalujte: pip install -e '.[dashboard]'[/dim]")
        return

    console.print(f"[green]Spouštím dashboard na http://localhost:{port}[/green]")
    subprocess.run([
        sys.executable, "-m", "streamlit", "run",
        dash_module.__file__,
        "--server.port", str(port),
        "--server.headless", "true",
    ])


if __name__ == "__main__":
    main()
