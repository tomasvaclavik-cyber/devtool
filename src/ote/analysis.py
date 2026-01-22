"""Modul pro analýzu cenových vzorců."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ote.db import NegativePriceHour


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


# --- Negative price analysis ---


@dataclass
class NegativePriceStats:
    """Statistiky negativních cen."""

    count: int
    avg_negative_price: float | None
    min_price: float | None
    hours_distribution: dict[int, int]


def get_negative_price_stats(
    conn: sqlite3.Connection,
    days_back: int = 30,
) -> NegativePriceStats:
    """Statistiky negativních cen.

    Args:
        conn: Databázové připojení.
        days_back: Počet dnů zpět pro analýzu.

    Returns:
        NegativePriceStats s počtem, průměrnou cenou, min cenou a distribucí.
    """
    from ote.db import get_negative_price_hours

    negative_hours = get_negative_price_hours(conn, days_back)

    if not negative_hours:
        return NegativePriceStats(
            count=0,
            avg_negative_price=None,
            min_price=None,
            hours_distribution={},
        )

    prices: list[float] = [h.price_czk for h in negative_hours]
    avg_price = sum(prices) / len(prices) if prices else None
    min_price_val = min(prices) if prices else None

    # Distribuce podle hodiny
    hours_dist: dict[int, int] = {}
    for h in negative_hours:
        hour = h.hour
        hours_dist[hour] = hours_dist.get(hour, 0) + 1

    return NegativePriceStats(
        count=len(negative_hours),
        avg_negative_price=avg_price,
        min_price=min_price_val,
        hours_distribution=hours_dist,
    )


def get_negative_price_hours_list(
    conn: sqlite3.Connection,
    days_back: int = 30,
) -> list[NegativePriceHour]:
    """Seznam všech hodin s negativní cenou.

    Args:
        conn: Databázové připojení.
        days_back: Počet dnů zpět.

    Returns:
        Seznam NegativePriceHour z ote.db.
    """
    from ote.db import get_negative_price_hours

    return get_negative_price_hours(conn, days_back)


def get_negative_price_forecast(
    conn: sqlite3.Connection,
) -> list[int]:
    """Predikce hodin s pravděpodobnou negativní cenou (zítra).

    Na základě vzorců z historie - vrátí hodiny které měly negativní
    cenu alespoň 3× za posledních 30 dnů.

    Args:
        conn: Databázové připojení.

    Returns:
        Seznam hodin (0-23) s pravděpodobnou negativní cenou.
    """
    stats = get_negative_price_stats(conn, days_back=30)
    hours_dist = stats.hours_distribution

    # Hodiny s alespoň 3 výskyty negativní ceny
    risky_hours = [hour for hour, count in hours_dist.items() if count >= 3]
    return sorted(risky_hours)


# --- Trends and distribution ---


@dataclass
class PriceDistribution:
    """Distribuce cen."""

    bins: list[str]
    counts: list[int]
    percentiles: dict[str, float]


@dataclass
class MovingAverageDay:
    """Denní data s klouzavými průměry."""

    date: date
    daily_avg: float
    ma7: float | None
    ma30: float | None


@dataclass
class PriceTrend:
    """Trend cen."""

    direction: str
    change_percent: float | None
    current_avg: float | None
    previous_avg: float | None


def get_price_distribution(
    conn: sqlite3.Connection,
    days_back: int = 30,
) -> PriceDistribution:
    """Distribuce cen pro histogram.

    Args:
        conn: Databázové připojení.
        days_back: Počet dnů zpět pro analýzu.

    Returns:
        PriceDistribution s biny, počty a percentily.
    """
    from datetime import date, timedelta

    from ote.db import get_prices_for_range

    end_date = date.today()
    start_date = end_date - timedelta(days=days_back)
    prices = get_prices_for_range(conn, start_date, end_date)

    if len(prices) < 10:
        return PriceDistribution(bins=[], counts=[], percentiles={})

    price_values = sorted([p.price_czk for p in prices])
    n = len(price_values)

    # Výpočet percentilů
    percentiles = {
        "p10": price_values[int(n * 0.10)],
        "p25": price_values[int(n * 0.25)],
        "p50": price_values[int(n * 0.50)],
        "p75": price_values[int(n * 0.75)],
        "p90": price_values[int(n * 0.90)],
    }

    # Vytvoření binů pro histogram
    min_price = min(price_values)
    max_price = max(price_values)
    num_bins = 20
    bin_width = (max_price - min_price) / num_bins if max_price > min_price else 1

    bins: list[str] = []
    counts: list[int] = []
    for i in range(num_bins):
        bin_start = min_price + i * bin_width
        bin_end = bin_start + bin_width
        bins.append(f"{bin_start:.0f}-{bin_end:.0f}")
        count = sum(1 for p in price_values if bin_start <= p < bin_end)
        counts.append(count)

    # Poslední bin zahrnuje i max hodnotu
    counts[-1] += sum(1 for p in price_values if p == max_price)

    return PriceDistribution(bins=bins, counts=counts, percentiles=percentiles)


def get_moving_averages(
    conn: sqlite3.Connection,
    days_back: int = 60,
) -> list[MovingAverageDay]:
    """Klouzavé průměry.

    Args:
        conn: Databázové připojení.
        days_back: Počet dnů zpět.

    Returns:
        Seznam MovingAverageDay s denním průměrem a MA.
    """
    from ote.db import get_daily_averages

    daily_avgs = get_daily_averages(conn, days_back)

    if not daily_avgs:
        return []

    result: list[MovingAverageDay] = []
    for i, day_data in enumerate(daily_avgs):
        # 7denní MA
        ma7: float | None = None
        if i >= 6:
            ma7_values = [daily_avgs[j].avg_price for j in range(i - 6, i + 1)]
            ma7 = sum(ma7_values) / len(ma7_values)

        # 30denní MA
        ma30: float | None = None
        if i >= 29:
            ma30_values = [daily_avgs[j].avg_price for j in range(i - 29, i + 1)]
            ma30 = sum(ma30_values) / len(ma30_values)

        result.append(MovingAverageDay(
            date=day_data.date,
            daily_avg=day_data.avg_price,
            ma7=ma7,
            ma30=ma30,
        ))

    return result


def get_price_trend(
    conn: sqlite3.Connection,
    days_back: int = 30,
) -> PriceTrend:
    """Trend cen.

    Args:
        conn: Databázové připojení.
        days_back: Počet dnů zpět.

    Returns:
        PriceTrend s směrem, změnou a průměry.
    """
    from ote.db import get_daily_averages

    # Potřebujeme 2× days_back pro porovnání s předchozím obdobím
    daily_avgs = get_daily_averages(conn, days_back * 2)

    if len(daily_avgs) < days_back:
        return PriceTrend(
            direction="nedostatek dat",
            change_percent=None,
            current_avg=None,
            previous_avg=None,
        )

    # Aktuální období (posledních days_back dnů)
    current_period = daily_avgs[-days_back:]
    current_avg = sum(d.avg_price for d in current_period) / len(current_period)

    # Předchozí období
    if len(daily_avgs) >= days_back * 2:
        previous_period = daily_avgs[-days_back * 2 : -days_back]
        previous_avg = sum(d.avg_price for d in previous_period) / len(previous_period)
    else:
        # Máme méně dat, použijeme co máme
        previous_period = daily_avgs[: -days_back]
        if previous_period:
            previous_avg = sum(d.avg_price for d in previous_period) / len(previous_period)
        else:
            return PriceTrend(
                direction="nedostatek dat",
                change_percent=None,
                current_avg=current_avg,
                previous_avg=None,
            )

    # Výpočet změny
    if previous_avg == 0:
        change_percent = 0.0
    else:
        change_percent = ((current_avg - previous_avg) / previous_avg) * 100

    # Určení směru
    if change_percent > 5:
        direction = "rostoucí"
    elif change_percent < -5:
        direction = "klesající"
    else:
        direction = "stabilní"

    return PriceTrend(
        direction=direction,
        change_percent=change_percent,
        current_avg=current_avg,
        previous_avg=previous_avg,
    )
