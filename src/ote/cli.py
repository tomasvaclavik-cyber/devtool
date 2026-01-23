"""Hlavní CLI rozhraní."""

from datetime import date

import click
import httpx
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ote import __version__
from ote.db import (
    get_available_dates,
    get_connection,
    get_daily_stats,
    get_default_db_path,
    get_prices_for_date,
    save_prices,
)
from ote.spot import fetch_spot_prices, get_current_price

# GitHub raw URL pro databázi (z data branch)
GITHUB_DB_URL = (
    "https://raw.githubusercontent.com/tomasvaclavik-cyber/devtool/data/data/prices.db"
)

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


@main.command()
@click.option("--force", "-f", is_flag=True, help="Přepsat lokální databázi bez dotazu")
def sync(force: bool) -> None:
    """Stáhne nejnovější databázi z GitHubu."""
    try:
        db_path = get_default_db_path()

        # Kontrola existence lokální DB
        if db_path.exists() and not force:
            console.print(f"[yellow]Lokální databáze existuje: {db_path}[/yellow]")
            if not click.confirm("Přepsat lokální databázi novější verzí z GitHubu?"):
                console.print("[dim]Zrušeno.[/dim]")
                return

        console.print("[cyan]Stahuji databázi z GitHubu...[/cyan]")

        # Stažení databáze
        response = httpx.get(GITHUB_DB_URL, follow_redirects=True, timeout=30.0)
        response.raise_for_status()

        # Uložení
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_path.write_bytes(response.content)

        size_kb = len(response.content) / 1024
        console.print(f"[green]Databáze stažena ({size_kb:.1f} KB)[/green]")
        console.print(f"[dim]Uloženo do: {db_path}[/dim]")

        # Zobraz počet dnů v DB
        conn = get_connection(db_path)
        dates = get_available_dates(conn)
        conn.close()

        if dates:
            console.print(f"[dim]Dostupná historie: {len(dates)} dnů[/dim]")
            console.print(f"[dim]Od {dates[-1]} do {dates[0]}[/dim]")

    except httpx.HTTPStatusError as e:
        console.print(f"[red]Chyba při stahování: HTTP {e.response.status_code}[/red]")
    except httpx.RequestError as e:
        console.print(f"[red]Chyba připojení: {e}[/red]")
    except Exception as e:
        console.print(f"[red]Chyba: {e}[/red]")


@main.command()
@click.option(
    "--date", "-d", "report_date", default=None, help="Datum (YYYY-MM-DD), výchozí dnes"
)
def benchmark(report_date: str | None) -> None:
    """Srovnání aktuální ceny s historií."""
    try:
        from ote.analysis import get_current_benchmark, get_daily_benchmark

        conn = get_connection()

        if report_date:
            dt = date.fromisoformat(report_date)
            bm = get_daily_benchmark(conn, dt)
            if not bm:
                console.print(f"[red]Žádná data pro {dt}[/red]")
                conn.close()
                return
            title = f"Benchmark pro {dt}"
        else:
            # Získej aktuální cenu z API
            prices, _ = fetch_spot_prices(date.today())
            current = get_current_price(prices)

            if not current:
                console.print("[red]Aktuální cena není k dispozici.[/red]")
                conn.close()
                return

            bm = get_current_benchmark(conn, current.price_czk)
            title = "Benchmark aktuální ceny"

        conn.close()

        # Barvy pro klasifikaci
        color_map = {
            "velmi levná": "green",
            "levná": "bright_green",
            "normální": "yellow",
            "drahá": "orange3",
            "velmi drahá": "red",
            "nedostatek dat": "dim",
        }
        color = color_map.get(bm.classification, "white")

        console.print()
        console.print(Panel(f"[bold {color}]{bm.classification.upper()}[/bold {color}]",
                           title=title, expand=False))
        console.print()

        table = Table(show_header=False, box=None)
        table.add_column("Metrika", style="cyan")
        table.add_column("Hodnota", justify="right")

        table.add_row("Aktuální cena", f"{bm.current_price:,.0f} CZK/MWh")
        table.add_row("Průměr 7 dnů", f"{bm.avg_7d:,.0f} CZK/MWh")
        table.add_row("Průměr 30 dnů", f"{bm.avg_30d:,.0f} CZK/MWh")
        table.add_row("Percentil", f"{bm.percentile_rank}. percentil")

        if bm.vs_yesterday_pct is not None:
            delta = "+" if bm.vs_yesterday_pct > 0 else ""
            table.add_row("Vs. včera", f"{delta}{bm.vs_yesterday_pct:.1f}%")

        if bm.vs_last_week_pct is not None:
            delta = "+" if bm.vs_last_week_pct > 0 else ""
            table.add_row("Vs. minulý týden", f"{delta}{bm.vs_last_week_pct:.1f}%")

        console.print(table)

    except Exception as e:
        console.print(f"[red]Chyba: {e}[/red]")


@main.command()
@click.option(
    "--name", "-n", default=None,
    help="Název profilu (ranní, home_office, večerní, noční, víkendový)"
)
@click.option("--optimal", is_flag=True, help="Zobrazit optimální (nejlevnější) profil")
def profile(name: str | None, optimal: bool) -> None:
    """Analýza spotřebitelských profilů."""
    try:
        from ote.analysis import (
            CONSUMPTION_PROFILES,
            analyze_consumption_profile,
            get_all_profiles_comparison,
            get_optimal_profile,
        )

        conn = get_connection()

        if optimal:
            opt = get_optimal_profile(conn)
            if opt:
                console.print(f"[green]Optimální profil: [bold]{opt}[/bold][/green]")
                profile_data = analyze_consumption_profile(conn, opt)
                if profile_data:
                    console.print(f"[dim]{profile_data.description}[/dim]")
                    avg_price = profile_data.avg_price_czk
                    console.print(f"[dim]Průměrná cena: {avg_price:,.0f} CZK/MWh[/dim]")
                    savings = profile_data.savings_vs_flat_pct
                    console.print(f"[dim]Úspora oproti flat tarifu: {savings:+.1f}%[/dim]")
            else:
                console.print("[yellow]Nedostatek dat pro výpočet optimálního profilu.[/yellow]")
            conn.close()
            return

        if name:
            if name not in CONSUMPTION_PROFILES:
                console.print(f"[red]Neznámý profil: {name}[/red]")
                console.print(f"[dim]Dostupné: {', '.join(CONSUMPTION_PROFILES.keys())}[/dim]")
                conn.close()
                return

            profile_data = analyze_consumption_profile(conn, name)
            if not profile_data:
                console.print("[yellow]Nedostatek dat pro analýzu profilu.[/yellow]")
                conn.close()
                return

            console.print()
            console.print(Panel(f"[bold]{name}[/bold]\n{profile_data.description}",
                               title="Spotřebitelský profil", expand=False))
            console.print()

            table = Table(show_header=False, box=None)
            table.add_column("Metrika", style="cyan")
            table.add_column("Hodnota", justify="right")

            hours_str = ", ".join(f"{h}:00" for h in profile_data.hours)
            table.add_row("Aktivní hodiny", hours_str)
            table.add_row("Průměrná cena (CZK)", f"{profile_data.avg_price_czk:,.0f} CZK/MWh")
            table.add_row("Průměrná cena (EUR)", f"{profile_data.avg_price_eur:,.2f} EUR/MWh")

            savings_color = "green" if profile_data.savings_vs_flat_pct > 0 else "red"
            table.add_row("Úspora vs flat tarif",
                         f"[{savings_color}]{profile_data.savings_vs_flat_pct:+.1f}%[/{savings_color}]")

            table.add_row("Nejlevnější den", profile_data.best_day)
            table.add_row("Nejdražší den", profile_data.worst_day)

            console.print(table)
        else:
            # Zobraz všechny profily
            profiles = get_all_profiles_comparison(conn)

            if not profiles:
                console.print("[yellow]Nedostatek dat pro analýzu profilů.[/yellow]")
                conn.close()
                return

            table = Table(title="Spotřebitelské profily (seřazeno od nejlevnějšího)")
            table.add_column("Profil", style="cyan")
            table.add_column("Popis")
            table.add_column("Cena (CZK/MWh)", justify="right", style="yellow")
            table.add_column("Úspora", justify="right")

            for i, p in enumerate(profiles):
                savings_color = "green" if p.savings_vs_flat_pct > 0 else "red"
                row_style = "bold" if i == 0 else None

                table.add_row(
                    p.name,
                    p.description,
                    f"{p.avg_price_czk:,.0f}",
                    f"[{savings_color}]{p.savings_vs_flat_pct:+.1f}%[/{savings_color}]",
                    style=row_style,
                )

            console.print(table)

        conn.close()

    except Exception as e:
        console.print(f"[red]Chyba: {e}[/red]")


@main.command()
@click.option("--trend", is_flag=True, help="Zobrazit trend volatility")
def volatility(trend: bool) -> None:
    """Zobrazí metriky cenové volatility."""
    try:
        from ote.analysis import get_volatility_metrics

        conn = get_connection()
        metrics = get_volatility_metrics(conn, days_back=30)
        conn.close()

        if metrics.volatility_trend == "nedostatek dat":
            console.print("[yellow]Nedostatek dat pro výpočet volatility.[/yellow]")
            return

        console.print()
        console.print(Panel("[bold]Metriky cenové volatility[/bold]", expand=False))
        console.print()

        table = Table(show_header=False, box=None)
        table.add_column("Metrika", style="cyan")
        table.add_column("Hodnota", justify="right")

        table.add_row("Denní volatilita (std dev)", f"{metrics.daily_volatility:,.0f} CZK/MWh")
        table.add_row("Intraday volatilita", f"{metrics.intraday_volatility:,.0f} CZK/MWh")
        table.add_row("Průměrné denní rozpětí", f"{metrics.avg_daily_swing:,.0f} CZK/MWh")
        table.add_row("Max denní rozpětí", f"{metrics.max_daily_swing:,.0f} CZK/MWh")
        table.add_row("VaR 95%", f"{metrics.var_95:,.0f} CZK/MWh")
        table.add_row("VaR 99%", f"{metrics.var_99:,.0f} CZK/MWh")

        trend_color = {
            "rostoucí": "red",
            "klesající": "green",
            "stabilní": "yellow",
        }.get(metrics.volatility_trend, "white")

        trend_text = metrics.volatility_trend
        table.add_row("Trend volatility", f"[{trend_color}]{trend_text}[/{trend_color}]")

        console.print(table)

    except Exception as e:
        console.print(f"[red]Chyba: {e}[/red]")


@main.command()
@click.option("--tomorrow", is_flag=True, help="Predikce špiček pro zítřek")
@click.option("--hours", is_flag=True, help="Distribuce špiček podle hodin")
def peaks(tomorrow: bool, hours: bool) -> None:
    """Analýza a predikce cenových špiček."""
    try:
        from ote.analysis import (
            get_peak_analysis,
            get_peak_probability_by_hour,
            predict_peaks_tomorrow,
        )

        conn = get_connection()

        if tomorrow:
            predictions = predict_peaks_tomorrow(conn)

            if not predictions:
                console.print("[yellow]Nedostatek dat pro predikci špiček.[/yellow]")
                conn.close()
                return

            # Filtruj pouze rizikové hodiny
            risky = [p for p in predictions if p.probability >= 0.2]

            if not risky:
                console.print("[green]Zítra se neočekávají výrazné cenové špičky.[/green]")
            else:
                console.print()
                title = "[bold red]Predikce špiček pro zítřek[/bold red]"
                console.print(Panel(title, expand=False))
                console.print()

                table = Table()
                table.add_column("Hodina", style="cyan")
                table.add_column("Pravděpodobnost", justify="right")
                table.add_column("Očekávaná cena", justify="right", style="yellow")
                table.add_column("Riziko", justify="center")

                for p in sorted(risky, key=lambda x: x.probability, reverse=True):
                    risk_color = {
                        "vysoké": "red",
                        "střední": "orange3",
                        "nízké": "green",
                    }.get(p.risk_level, "white")

                    table.add_row(
                        f"{p.hour:02d}:00",
                        f"{p.probability * 100:.0f}%",
                        f"{p.expected_price:,.0f} CZK/MWh",
                        f"[{risk_color}]{p.risk_level}[/{risk_color}]",
                    )

                console.print(table)

        elif hours:
            probs = get_peak_probability_by_hour(conn)

            console.print()
            console.print(Panel("[bold]Pravděpodobnost špičky podle hodiny[/bold]", expand=False))
            console.print()

            # Jednoduchý textový bar chart
            for hour in range(24):
                prob = probs.get(hour, 0)
                bar_len = int(prob * 40)
                bar = "█" * bar_len
                color = "red" if prob >= 0.5 else "orange3" if prob >= 0.2 else "green"
                console.print(f"{hour:02d}:00 [{color}]{bar}[/{color}] {prob * 100:.0f}%")

        else:
            analysis = get_peak_analysis(conn)

            if analysis.total_peaks_30d == 0:
                console.print("[yellow]Žádné cenové špičky za posledních 30 dnů.[/yellow]")
                conn.close()
                return

            console.print()
            console.print(Panel("[bold]Analýza cenových špiček (30 dnů)[/bold]", expand=False))
            console.print()

            table = Table(show_header=False, box=None)
            table.add_column("Metrika", style="cyan")
            table.add_column("Hodnota", justify="right")

            table.add_row("Hranice špičky (P90)", f"{analysis.threshold_p90:,.0f} CZK/MWh")
            table.add_row("Celkem špiček", f"{analysis.total_peaks_30d}")
            table.add_row("Průměrná cena špičky", f"{analysis.avg_peak_price:,.0f} CZK/MWh")
            table.add_row("Max cena špičky", f"{analysis.max_peak_price:,.0f} CZK/MWh")

            risky_hours = ", ".join(f"{h:02d}:00" for h in analysis.most_risky_hours)
            table.add_row("Nejrizikovější hodiny", risky_hours)

            console.print(table)

        conn.close()

    except Exception as e:
        console.print(f"[red]Chyba: {e}[/red]")


@main.command()
@click.option("--correlation", is_flag=True, help="Zobrazit korelaci počasí a cen")
def weather(correlation: bool) -> None:
    """Předpověď počasí a její vliv na ceny elektřiny."""
    try:
        from ote.weather import fetch_weather_forecast, get_weather_price_correlation

        if correlation:
            conn = get_connection()
            corr = get_weather_price_correlation(conn, days_back=30)
            conn.close()

            if not corr:
                console.print("[yellow]Nedostatek dat pro korelační analýzu.[/yellow]")
                return

            console.print()
            console.print(Panel("[bold]Korelace počasí a cen elektřiny[/bold]", expand=False))
            console.print()

            table = Table(show_header=False, box=None)
            table.add_column("Faktor", style="cyan")
            table.add_column("Korelace", justify="right")

            def corr_color(c: float) -> str:
                if abs(c) >= 0.5:
                    return "bold"
                return "dim" if abs(c) < 0.2 else ""

            table.add_row("Teplota",
                         f"[{corr_color(corr.temperature_correlation)}]{corr.temperature_correlation:+.3f}[/]")
            table.add_row("Oblačnost",
                         f"[{corr_color(corr.cloud_cover_correlation)}]{corr.cloud_cover_correlation:+.3f}[/]")
            table.add_row("Sluneční záření",
                         f"[{corr_color(corr.solar_radiation_correlation)}]{corr.solar_radiation_correlation:+.3f}[/]")
            table.add_row("Rychlost větru",
                         f"[{corr_color(corr.wind_speed_correlation)}]{corr.wind_speed_correlation:+.3f}[/]")

            console.print(table)
            console.print()
            console.print(f"[bold]Nejsilnější faktor:[/bold] {corr.strongest_factor}")
            console.print(f"[dim]R² = {corr.r_squared:.3f}[/dim]")

        else:
            console.print("[cyan]Načítám předpověď počasí...[/cyan]")
            forecasts = fetch_weather_forecast(days_ahead=7)

            if not forecasts:
                console.print("[red]Nepodařilo se načíst předpověď počasí.[/red]")
                return

            table = Table(title="Předpověď počasí (Praha)")
            table.add_column("Datum", style="cyan")
            table.add_column("Typ")
            table.add_column("Teplota", justify="right")
            table.add_column("Oblačnost", justify="right")
            table.add_column("Vítr", justify="right")
            table.add_column("Vliv na ceny")

            type_icons = {
                "sunny": "☀️  slunečno",
                "cloudy": "☁️  zataženo",
                "windy": "💨 větrno",
                "mixed": "🌤️  proměnlivé",
            }

            for f in forecasts:
                # Odhad vlivu na ceny
                if f.weather_type == "sunny":
                    impact = "[green]↓ nižší[/green]"
                elif f.weather_type == "windy":
                    impact = "[green]↓ nižší[/green]"
                elif f.weather_type == "cloudy":
                    impact = "[red]↑ vyšší[/red]"
                else:
                    impact = "[yellow]~ běžné[/yellow]"

                table.add_row(
                    f.date.strftime("%a %d.%m"),
                    type_icons.get(f.weather_type, f.weather_type),
                    f"{f.avg_temperature:.1f}°C",
                    f"{f.avg_cloud_cover:.0f}%",
                    f"{f.avg_wind_speed:.1f} m/s",
                    impact,
                )

            console.print(table)

    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
    except Exception as e:
        console.print(f"[red]Chyba: {e}[/red]")


@main.command()
@click.option(
    "--date", "-d", "report_date", default=None, help="Datum (YYYY-MM-DD)"
)
@click.option(
    "--weather", "-w", "use_weather", is_flag=True,
    help="Použít počasí-enhanced predikci"
)
@click.option("--days", default=7, help="Počet dnů dopředu (výchozí 7)")
def forecast(report_date: str | None, use_weather: bool, days: int) -> None:
    """Predikce cen elektřiny."""
    try:
        from ote.forecast import (
            forecast_statistical,
            forecast_weather_enhanced,
            get_data_sufficiency,
            get_forecast_for_days,
            get_forecast_for_days_with_weather,
        )

        conn = get_connection()
        sufficiency = get_data_sufficiency(conn)

        if not sufficiency.can_show_hourly_patterns:
            console.print(
                f"[yellow]Pro predikci je potřeba alespoň 7 dnů dat. "
                f"Aktuálně máte {sufficiency.total_days} dnů.[/yellow]"
            )
            conn.close()
            return

        if report_date:
            # Predikce pro konkrétní den
            dt = date.fromisoformat(report_date)

            if use_weather:
                forecasts = forecast_weather_enhanced(conn, dt)
                method = "počasí-enhanced"
            else:
                forecasts = forecast_statistical(conn, dt)
                method = "statistická"

            if not forecasts:
                console.print("[yellow]Nepodařilo se vytvořit predikci.[/yellow]")
                conn.close()
                return

            # Agreguj na hodinové průměry
            hourly: dict[int, list[float]] = {}
            for f in forecasts:
                h = f.time_from.hour
                if h not in hourly:
                    hourly[h] = []
                hourly[h].append(f.price_czk)

            table = Table(title=f"Predikce pro {dt} ({method})")
            table.add_column("Hodina", style="cyan")
            table.add_column("Predikce (CZK/MWh)", justify="right", style="yellow")

            for h in sorted(hourly.keys()):
                avg = sum(hourly[h]) / len(hourly[h])
                table.add_row(f"{h:02d}:00", f"{avg:,.0f}")

            console.print(table)

        else:
            # Přehled predikcí D+2 až D+days
            if use_weather:
                all_forecasts = get_forecast_for_days_with_weather(conn, days_ahead=days)
                method = "počasí-enhanced"
            else:
                all_forecasts = get_forecast_for_days(conn, days_ahead=days)
                method = "statistická"

            if not all_forecasts:
                console.print("[yellow]Nepodařilo se vytvořit predikce.[/yellow]")
                conn.close()
                return

            table = Table(title=f"Predikce D+2 až D+{days} ({method})")
            table.add_column("Datum", style="cyan")
            table.add_column("Min", justify="right")
            table.add_column("Max", justify="right")
            table.add_column("Průměr", justify="right", style="yellow")

            for dt, forecasts in sorted(all_forecasts.items()):
                prices = [f.price_czk for f in forecasts]
                table.add_row(
                    dt.strftime("%a %d.%m"),
                    f"{min(prices):,.0f}",
                    f"{max(prices):,.0f}",
                    f"{sum(prices) / len(prices):,.0f}",
                )

            console.print(table)

        conn.close()

    except Exception as e:
        console.print(f"[red]Chyba: {e}[/red]")


if __name__ == "__main__":
    main()
