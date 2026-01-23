"""Modul pro analýzu cenových vzorců."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ote.db import NegativePriceHour


# --- Consumption Profiles ---


@dataclass
class ProfileDefinition:
    """Definice spotřebitelského profilu."""

    hours: list[int]
    desc: str


CONSUMPTION_PROFILES: dict[str, ProfileDefinition] = {
    "ranní": ProfileDefinition(hours=[5, 6, 7, 8], desc="Spotřeba brzy ráno (5-9h)"),
    "home_office": ProfileDefinition(
        hours=[8, 9, 10, 11, 12, 13, 14, 15, 16],
        desc="Práce z domova (8-17h)",
    ),
    "večerní": ProfileDefinition(
        hours=[17, 18, 19, 20, 21, 22], desc="Večerní spotřeba (17-23h)"
    ),
    "noční": ProfileDefinition(
        hours=[22, 23, 0, 1, 2, 3, 4, 5], desc="Noční tarif (22-6h)"
    ),
    "víkendový": ProfileDefinition(
        hours=[8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
        desc="Denní spotřeba o víkendech (8-19h)",
    ),
}


# --- Dataclasses ---


@dataclass
class PriceBenchmark:
    """Srovnání aktuální ceny s historií."""

    current_price: float
    avg_7d: float
    avg_30d: float
    percentile_rank: int  # 0-100 (kde se nachází aktuální cena)
    vs_yesterday_pct: float | None  # % změna oproti včerejšku
    vs_last_week_pct: float | None  # % změna oproti minulému týdnu
    classification: str  # "velmi levná" až "velmi drahá"


@dataclass
class ConsumptionProfile:
    """Analýza pro spotřebitelský profil."""

    name: str
    description: str
    hours: list[int]
    avg_price_czk: float
    avg_price_eur: float
    savings_vs_flat_pct: float  # % úspora oproti celkovému průměru
    best_day: str  # nejlevnější den v týdnu
    worst_day: str  # nejdražší den v týdnu


@dataclass
class VolatilityMetrics:
    """Metriky cenové volatility."""

    daily_volatility: float  # std dev denních průměrů
    intraday_volatility: float  # průměrná std dev v rámci dne
    max_daily_swing: float  # největší denní rozpětí (max-min)
    avg_daily_swing: float  # průměrné denní rozpětí
    var_95: float  # 95% Value at Risk (CZK/MWh)
    var_99: float  # 99% VaR
    volatility_trend: str  # "rostoucí", "klesající", "stabilní"


@dataclass
class PeakPrediction:
    """Predikce cenové špičky."""

    hour: int
    probability: float  # 0.0 - 1.0
    expected_price: float
    confidence_low: float
    confidence_high: float
    historical_peak_count: int  # kolikrát byla špička za 30 dnů
    risk_level: str  # "nízké", "střední", "vysoké"


@dataclass
class PeakAnalysis:
    """Analýza cenových špiček."""

    threshold_p90: float  # hranice pro špičku (90. percentil)
    total_peaks_30d: int  # celkový počet špiček
    peak_hours_distribution: dict[int, int]  # hodina -> počet
    most_risky_hours: list[int]  # top 5 nejrizikovějších hodin
    avg_peak_price: float
    max_peak_price: float


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


# --- Benchmark Analysis ---


def get_current_benchmark(
    conn: sqlite3.Connection,
    current_price: float,
    days_back: int = 30,
) -> PriceBenchmark:
    """Srovnání aktuální ceny s historií.

    Args:
        conn: Databázové připojení.
        current_price: Aktuální cena (CZK/MWh).
        days_back: Počet dnů zpět pro analýzu.

    Returns:
        PriceBenchmark s porovnáním.
    """
    from ote.db import get_daily_averages, get_prices_for_range

    today = date.today()
    start_date = today - timedelta(days=days_back)

    # Získej všechny ceny
    prices = get_prices_for_range(conn, start_date, today)
    all_prices = sorted([p.price_czk for p in prices])

    if len(all_prices) < 10:
        return PriceBenchmark(
            current_price=current_price,
            avg_7d=0.0,
            avg_30d=0.0,
            percentile_rank=50,
            vs_yesterday_pct=None,
            vs_last_week_pct=None,
            classification="nedostatek dat",
        )

    # Percentilové zařazení
    below_count = sum(1 for p in all_prices if p < current_price)
    percentile_rank = int((below_count / len(all_prices)) * 100)

    # Průměry
    daily_avgs = get_daily_averages(conn, days_back)

    avg_7d = 0.0
    avg_30d = 0.0
    vs_yesterday_pct = None
    vs_last_week_pct = None

    if daily_avgs:
        # 30denní průměr
        avg_30d = sum(d.avg_price for d in daily_avgs) / len(daily_avgs)

        # 7denní průměr
        last_7 = daily_avgs[-7:] if len(daily_avgs) >= 7 else daily_avgs
        avg_7d = sum(d.avg_price for d in last_7) / len(last_7)

        # Včerejší průměr
        if len(daily_avgs) >= 1:
            yesterday_avg = daily_avgs[-1].avg_price
            if yesterday_avg != 0:
                vs_yesterday_pct = ((current_price - yesterday_avg) / yesterday_avg) * 100

        # Minulý týden
        if len(daily_avgs) >= 8:
            last_week_avg = daily_avgs[-8].avg_price
            if last_week_avg != 0:
                vs_last_week_pct = ((current_price - last_week_avg) / last_week_avg) * 100

    # Klasifikace podle percentilu
    if percentile_rank <= 10:
        classification = "velmi levná"
    elif percentile_rank <= 30:
        classification = "levná"
    elif percentile_rank <= 70:
        classification = "normální"
    elif percentile_rank <= 90:
        classification = "drahá"
    else:
        classification = "velmi drahá"

    return PriceBenchmark(
        current_price=current_price,
        avg_7d=avg_7d,
        avg_30d=avg_30d,
        percentile_rank=percentile_rank,
        vs_yesterday_pct=vs_yesterday_pct,
        vs_last_week_pct=vs_last_week_pct,
        classification=classification,
    )


def get_daily_benchmark(
    conn: sqlite3.Connection,
    target_date: date,
    days_back: int = 30,
) -> PriceBenchmark | None:
    """Srovnání denního průměru s historií.

    Args:
        conn: Databázové připojení.
        target_date: Datum pro srovnání.
        days_back: Počet dnů zpět pro analýzu.

    Returns:
        PriceBenchmark nebo None pokud nejsou data.
    """
    from ote.db import get_daily_stats

    stats = get_daily_stats(conn, target_date)
    if not stats:
        return None

    return get_current_benchmark(conn, stats["avg"], days_back)


# --- Consumption Profiles ---


def analyze_consumption_profile(
    conn: sqlite3.Connection,
    profile_name: str,
    days_back: int = 30,
) -> ConsumptionProfile | None:
    """Analyzuje cenový profil pro daný typ spotřeby.

    Args:
        conn: Databázové připojení.
        profile_name: Název profilu (z CONSUMPTION_PROFILES).
        days_back: Počet dnů zpět pro analýzu.

    Returns:
        ConsumptionProfile nebo None pokud profil neexistuje.
    """
    from ote.db import get_overall_stats, get_prices_for_range, get_weekday_aggregates

    if profile_name not in CONSUMPTION_PROFILES:
        return None

    profile_def = CONSUMPTION_PROFILES[profile_name]
    hours = profile_def.hours
    description = profile_def.desc

    today = date.today()
    start_date = today - timedelta(days=days_back)

    # Získej všechny ceny
    prices = get_prices_for_range(conn, start_date, today)

    if not prices:
        return None

    # Filtruj ceny pro hodiny profilu
    profile_prices_czk: list[float] = []
    profile_prices_eur: list[float] = []

    for p in prices:
        if p.time_from.hour in hours:
            profile_prices_czk.append(p.price_czk)
            profile_prices_eur.append(p.price_eur)

    if not profile_prices_czk:
        return None

    avg_price_czk = sum(profile_prices_czk) / len(profile_prices_czk)
    avg_price_eur = sum(profile_prices_eur) / len(profile_prices_eur)

    # Celkový průměr pro výpočet úspory
    overall_stats = get_overall_stats(conn, days_back)
    if overall_stats:
        flat_avg = overall_stats["avg"]
        if flat_avg != 0:
            savings_vs_flat_pct = ((flat_avg - avg_price_czk) / flat_avg) * 100
        else:
            savings_vs_flat_pct = 0.0
    else:
        savings_vs_flat_pct = 0.0

    # Nejlevnější a nejdražší den v týdnu
    weekday_aggregates = get_weekday_aggregates(conn, days_back)
    weekday_names = ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"]

    # Průměry pro profil podle dne v týdnu
    weekday_sums: dict[int, list[float]] = {i: [] for i in range(7)}
    for agg in weekday_aggregates:
        if int(agg["hour"]) in hours:
            weekday_sums[int(agg["weekday"])].append(float(agg["avg_price"]))

    weekday_avgs: dict[int, float] = {}
    for wd, price_list in weekday_sums.items():
        if price_list:
            weekday_avgs[wd] = sum(price_list) / len(price_list)

    if weekday_avgs:
        best_wd = min(weekday_avgs, key=lambda w: weekday_avgs[w])
        worst_wd = max(weekday_avgs, key=lambda w: weekday_avgs[w])
        best_day = weekday_names[best_wd]
        worst_day = weekday_names[worst_wd]
    else:
        best_day = "N/A"
        worst_day = "N/A"

    return ConsumptionProfile(
        name=profile_name,
        description=description,
        hours=list(hours),
        avg_price_czk=avg_price_czk,
        avg_price_eur=avg_price_eur,
        savings_vs_flat_pct=savings_vs_flat_pct,
        best_day=best_day,
        worst_day=worst_day,
    )


def get_all_profiles_comparison(
    conn: sqlite3.Connection,
    days_back: int = 30,
) -> list[ConsumptionProfile]:
    """Porovnání všech profilů spotřeby.

    Args:
        conn: Databázové připojení.
        days_back: Počet dnů zpět pro analýzu.

    Returns:
        Seznam profilů seřazený od nejlevnějšího.
    """
    profiles: list[ConsumptionProfile] = []

    for name in CONSUMPTION_PROFILES:
        profile = analyze_consumption_profile(conn, name, days_back)
        if profile:
            profiles.append(profile)

    # Seřaď podle průměrné ceny
    return sorted(profiles, key=lambda p: p.avg_price_czk)


def get_optimal_profile(
    conn: sqlite3.Connection,
    days_back: int = 30,
) -> str | None:
    """Najde optimální (nejlevnější) profil spotřeby.

    Args:
        conn: Databázové připojení.
        days_back: Počet dnů zpět pro analýzu.

    Returns:
        Název optimálního profilu nebo None.
    """
    profiles = get_all_profiles_comparison(conn, days_back)
    if profiles:
        return profiles[0].name
    return None


# --- Volatility and Risk ---


def get_volatility_metrics(
    conn: sqlite3.Connection,
    days_back: int = 30,
) -> VolatilityMetrics:
    """Metriky cenové volatility.

    Args:
        conn: Databázové připojení.
        days_back: Počet dnů zpět pro analýzu.

    Returns:
        VolatilityMetrics.
    """
    from ote.db import get_daily_averages, get_prices_for_range

    today = date.today()
    start_date = today - timedelta(days=days_back)

    # Denní průměry pro volatilitu mezi dny
    daily_avgs = get_daily_averages(conn, days_back)

    if len(daily_avgs) < 3:
        return VolatilityMetrics(
            daily_volatility=0.0,
            intraday_volatility=0.0,
            max_daily_swing=0.0,
            avg_daily_swing=0.0,
            var_95=0.0,
            var_99=0.0,
            volatility_trend="nedostatek dat",
        )

    # Směrodatná odchylka denních průměrů
    daily_prices = [d.avg_price for d in daily_avgs]
    daily_mean = sum(daily_prices) / len(daily_prices)
    daily_variance = sum((p - daily_mean) ** 2 for p in daily_prices) / len(daily_prices)
    daily_volatility = daily_variance**0.5

    # Průměrné a maximální denní rozpětí
    daily_swings = [d.max_price - d.min_price for d in daily_avgs]
    avg_daily_swing = sum(daily_swings) / len(daily_swings)
    max_daily_swing = max(daily_swings)

    # Intraday volatilita - průměrná std dev v rámci dne
    prices = get_prices_for_range(conn, start_date, today)

    # Seskup podle dne
    daily_prices_lists: dict[date, list[float]] = {}
    for p in prices:
        d = p.time_from.date()
        if d not in daily_prices_lists:
            daily_prices_lists[d] = []
        daily_prices_lists[d].append(p.price_czk)

    intraday_stds: list[float] = []
    for day_prices in daily_prices_lists.values():
        if len(day_prices) >= 2:
            mean = sum(day_prices) / len(day_prices)
            var = sum((p - mean) ** 2 for p in day_prices) / len(day_prices)
            intraday_stds.append(var**0.5)

    intraday_volatility = sum(intraday_stds) / len(intraday_stds) if intraday_stds else 0.0

    # Value at Risk (VaR) - percentily
    all_prices = sorted([p.price_czk for p in prices])
    n = len(all_prices)
    if n >= 20:
        var_95 = all_prices[int(n * 0.95)]
        var_99 = all_prices[int(n * 0.99)]
    else:
        var_95 = max(all_prices) if all_prices else 0.0
        var_99 = max(all_prices) if all_prices else 0.0

    # Trend volatility - porovnání první a druhé poloviny období
    mid = len(daily_swings) // 2
    if mid >= 3:
        first_half_vol = sum(daily_swings[:mid]) / mid
        second_half_vol = sum(daily_swings[mid:]) / (len(daily_swings) - mid)

        if second_half_vol > first_half_vol * 1.1:
            volatility_trend = "rostoucí"
        elif second_half_vol < first_half_vol * 0.9:
            volatility_trend = "klesající"
        else:
            volatility_trend = "stabilní"
    else:
        volatility_trend = "nedostatek dat"

    return VolatilityMetrics(
        daily_volatility=daily_volatility,
        intraday_volatility=intraday_volatility,
        max_daily_swing=max_daily_swing,
        avg_daily_swing=avg_daily_swing,
        var_95=var_95,
        var_99=var_99,
        volatility_trend=volatility_trend,
    )


# --- Peak Detection and Prediction ---


def get_peak_analysis(
    conn: sqlite3.Connection,
    days_back: int = 30,
) -> PeakAnalysis:
    """Analýza cenových špiček.

    Args:
        conn: Databázové připojení.
        days_back: Počet dnů zpět pro analýzu.

    Returns:
        PeakAnalysis.
    """
    from ote.db import get_prices_for_range

    today = date.today()
    start_date = today - timedelta(days=days_back)

    prices = get_prices_for_range(conn, start_date, today)

    if len(prices) < 20:
        return PeakAnalysis(
            threshold_p90=0.0,
            total_peaks_30d=0,
            peak_hours_distribution={},
            most_risky_hours=[],
            avg_peak_price=0.0,
            max_peak_price=0.0,
        )

    all_prices = sorted([p.price_czk for p in prices])
    n = len(all_prices)

    # 90. percentil jako hranice špičky
    threshold_p90 = all_prices[int(n * 0.90)]

    # Počítání špiček
    peak_hours_distribution: dict[int, int] = {}
    peak_prices: list[float] = []

    for p in prices:
        if p.price_czk >= threshold_p90:
            hour = p.time_from.hour
            peak_hours_distribution[hour] = peak_hours_distribution.get(hour, 0) + 1
            peak_prices.append(p.price_czk)

    total_peaks = len(peak_prices)
    avg_peak_price = sum(peak_prices) / len(peak_prices) if peak_prices else 0.0
    max_peak_price = max(peak_prices) if peak_prices else 0.0

    # Top 5 nejrizikovějších hodin
    sorted_hours = sorted(
        peak_hours_distribution.items(), key=lambda x: x[1], reverse=True
    )
    most_risky_hours = [h for h, _ in sorted_hours[:5]]

    return PeakAnalysis(
        threshold_p90=threshold_p90,
        total_peaks_30d=total_peaks,
        peak_hours_distribution=peak_hours_distribution,
        most_risky_hours=most_risky_hours,
        avg_peak_price=avg_peak_price,
        max_peak_price=max_peak_price,
    )


def get_peak_probability_by_hour(
    conn: sqlite3.Connection,
    days_back: int = 30,
) -> dict[int, float]:
    """Pravděpodobnost špičky podle hodiny.

    Args:
        conn: Databázové připojení.
        days_back: Počet dnů zpět pro analýzu.

    Returns:
        Slovník {hodina: pravděpodobnost 0-1}.
    """
    peak_analysis = get_peak_analysis(conn, days_back)

    if not peak_analysis.peak_hours_distribution:
        return {h: 0.0 for h in range(24)}

    total = sum(peak_analysis.peak_hours_distribution.values())

    if total == 0:
        return {h: 0.0 for h in range(24)}

    # Normalizace na počet dnů
    probabilities: dict[int, float] = {}
    for hour in range(24):
        count = peak_analysis.peak_hours_distribution.get(hour, 0)
        # Počet špiček / počet dnů = pravděpodobnost
        probabilities[hour] = min(1.0, count / days_back)

    return probabilities


def predict_peaks_tomorrow(
    conn: sqlite3.Connection,
    days_back: int = 30,
) -> list[PeakPrediction]:
    """Predikce špiček pro zítřek.

    Args:
        conn: Databázové připojení.
        days_back: Počet dnů zpět pro analýzu.

    Returns:
        Seznam PeakPrediction pro každou hodinu.
    """
    from ote.db import get_prices_for_range, get_weekday_aggregates

    tomorrow = date.today() + timedelta(days=1)
    weekday = tomorrow.weekday()

    peak_analysis = get_peak_analysis(conn, days_back)
    probabilities = get_peak_probability_by_hour(conn, days_back)

    # Získej vzorce pro den v týdnu
    weekday_aggregates = get_weekday_aggregates(conn, days_back * 2)
    weekday_data = {
        agg["hour"]: agg for agg in weekday_aggregates if agg["weekday"] == weekday
    }

    # Fallback na hodinové průměry
    from ote.db import get_hourly_aggregates

    hourly_fallback = {agg["hour"]: agg for agg in get_hourly_aggregates(conn, days_back)}

    # Historická std dev pro confidence intervaly
    today = date.today()
    start_date = today - timedelta(days=days_back)
    prices = get_prices_for_range(conn, start_date, today)

    hourly_prices: dict[int, list[float]] = {h: [] for h in range(24)}
    for p in prices:
        hourly_prices[p.time_from.hour].append(p.price_czk)

    predictions: list[PeakPrediction] = []

    for hour in range(24):
        data = weekday_data.get(hour) or hourly_fallback.get(hour)

        if not data:
            continue

        expected_price = data["avg_price"]
        prob = probabilities.get(hour, 0.0)

        # Confidence interval
        prices_for_hour = hourly_prices.get(hour, [])
        if len(prices_for_hour) >= 2:
            mean = sum(prices_for_hour) / len(prices_for_hour)
            variance = sum((p - mean) ** 2 for p in prices_for_hour) / len(prices_for_hour)
            std = variance**0.5
            confidence_low = max(0, expected_price - 1.96 * std)
            confidence_high = expected_price + 1.96 * std
        else:
            confidence_low = expected_price * 0.7
            confidence_high = expected_price * 1.3

        # Historický počet špiček pro tuto hodinu
        historical_count = peak_analysis.peak_hours_distribution.get(hour, 0)

        # Úroveň rizika
        if prob >= 0.5:
            risk_level = "vysoké"
        elif prob >= 0.2:
            risk_level = "střední"
        else:
            risk_level = "nízké"

        predictions.append(
            PeakPrediction(
                hour=hour,
                probability=prob,
                expected_price=expected_price,
                confidence_low=confidence_low,
                confidence_high=confidence_high,
                historical_peak_count=historical_count,
                risk_level=risk_level,
            )
        )

    return predictions


def is_price_peak(
    conn: sqlite3.Connection,
    current_price: float,
    days_back: int = 30,
) -> bool:
    """Zjistí zda je aktuální cena špička.

    Args:
        conn: Databázové připojení.
        current_price: Aktuální cena (CZK/MWh).
        days_back: Počet dnů zpět pro analýzu.

    Returns:
        True pokud je cena nad 90. percentilem.
    """
    peak_analysis = get_peak_analysis(conn, days_back)
    return current_price >= peak_analysis.threshold_p90
