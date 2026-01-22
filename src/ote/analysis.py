"""Modul pro analýzu cenových vzorců."""

import sqlite3
from dataclasses import dataclass


@dataclass
class HourlyPattern:
    """Hodinový cenový vzorec."""

    hour: int
    avg_price: float
    min_price: float
    max_price: float
    sample_count: int


def get_hourly_patterns(
    conn: sqlite3.Connection,
    days_back: int = 30,
) -> list[HourlyPattern]:
    """Získá průměrné cenové vzorce podle hodiny.

    Args:
        conn: Databázové připojení.
        days_back: Počet dnů zpět pro analýzu.

    Returns:
        Seznam hodinových vzorců seřazený podle hodiny.
    """
    from ote.db import get_hourly_aggregates

    aggregates = get_hourly_aggregates(conn, days_back)

    return [
        HourlyPattern(
            hour=int(agg["hour"]),
            avg_price=agg["avg_price"],
            min_price=agg["min_price"],
            max_price=agg["max_price"],
            sample_count=int(agg["count"]),
        )
        for agg in aggregates
    ]


def get_best_hours(
    conn: sqlite3.Connection,
    top_n: int = 5,
    days_back: int = 30,
) -> list[tuple[int, float]]:
    """Vrátí nejlevnější hodiny pro spotřebu.

    Args:
        conn: Databázové připojení.
        top_n: Počet hodin k vrácení.
        days_back: Počet dnů zpět pro analýzu.

    Returns:
        Seznam (hodina, průměrná cena) seřazený od nejlevnější.
    """
    patterns = get_hourly_patterns(conn, days_back)
    sorted_patterns = sorted(patterns, key=lambda p: p.avg_price)
    return [(p.hour, p.avg_price) for p in sorted_patterns[:top_n]]


def get_worst_hours(
    conn: sqlite3.Connection,
    top_n: int = 5,
    days_back: int = 30,
) -> list[tuple[int, float]]:
    """Vrátí nejdražší hodiny (peak hours).

    Args:
        conn: Databázové připojení.
        top_n: Počet hodin k vrácení.
        days_back: Počet dnů zpět pro analýzu.

    Returns:
        Seznam (hodina, průměrná cena) seřazený od nejdražší.
    """
    patterns = get_hourly_patterns(conn, days_back)
    sorted_patterns = sorted(patterns, key=lambda p: p.avg_price, reverse=True)
    return [(p.hour, p.avg_price) for p in sorted_patterns[:top_n]]


def classify_price(
    price: float,
    conn: sqlite3.Connection,
    days_back: int = 30,
) -> str:
    """Klasifikuje cenu vzhledem k historickým datům.

    Args:
        price: Cena k klasifikaci (CZK/MWh).
        conn: Databázové připojení.
        days_back: Počet dnů zpět pro výpočet percentilů.

    Returns:
        Klasifikace: 'velmi levná', 'levná', 'normální', 'drahá', 'velmi drahá'.
    """
    from datetime import date, timedelta

    from ote.db import get_overall_stats, get_prices_for_range

    stats = get_overall_stats(conn, days_back)

    if not stats or stats["count"] < 10:
        return "nedostatek dat"

    # Získej všechny ceny pro výpočet percentilů
    end_date = date.today()
    start_date = end_date - timedelta(days=days_back)
    prices = get_prices_for_range(conn, start_date, end_date)

    if len(prices) < 10:
        return "nedostatek dat"

    # Seřaď ceny pro výpočet percentilů
    sorted_prices = sorted([p.price_czk for p in prices])
    n = len(sorted_prices)

    p10 = sorted_prices[int(n * 0.10)]
    p30 = sorted_prices[int(n * 0.30)]
    p70 = sorted_prices[int(n * 0.70)]
    p90 = sorted_prices[int(n * 0.90)]

    if price <= p10:
        return "velmi levná"
    elif price <= p30:
        return "levná"
    elif price <= p70:
        return "normální"
    elif price <= p90:
        return "drahá"
    else:
        return "velmi drahá"


def get_price_level_color(classification: str) -> str:
    """Vrátí barvu pro danou klasifikaci ceny."""
    colors = {
        "velmi levná": "#28a745",  # zelená
        "levná": "#7cb342",  # světle zelená
        "normální": "#ffc107",  # žlutá
        "drahá": "#ff9800",  # oranžová
        "velmi drahá": "#dc3545",  # červená
        "nedostatek dat": "#6c757d",  # šedá
    }
    return colors.get(classification, "#6c757d")


def get_weekday_hour_heatmap_data(
    conn: sqlite3.Connection,
    days_back: int = 60,
) -> list[dict[str, object]]:
    """Získá data pro heatmapu hodina × den v týdnu.

    Args:
        conn: Databázové připojení.
        days_back: Počet dnů zpět pro analýzu.

    Returns:
        Seznam slovníků s klíči: weekday, hour, avg_price, weekday_name.
    """
    from ote.db import get_weekday_aggregates

    weekday_names = ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"]

    aggregates = get_weekday_aggregates(conn, days_back)

    return [
        {
            "weekday": agg["weekday"],
            "weekday_name": weekday_names[int(agg["weekday"])],
            "hour": agg["hour"],
            "avg_price": agg["avg_price"],
        }
        for agg in aggregates
    ]
