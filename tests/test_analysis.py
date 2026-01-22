"""Testy pro modul analýzy."""

import sqlite3
from datetime import date, datetime, timedelta

import pytest

from ote.analysis import (
    HourlyPattern,
    MovingAverageDay,
    NegativePriceStats,
    PriceDistribution,
    PriceTrend,
    classify_price,
    get_best_hours,
    get_hourly_patterns,
    get_moving_averages,
    get_negative_price_forecast,
    get_negative_price_hours_list,
    get_negative_price_stats,
    get_price_distribution,
    get_price_level_color,
    get_price_trend,
    get_weekday_hour_heatmap_data,
    get_worst_hours,
)
from ote.db import init_db, save_prices
from ote.spot import SpotPrice


@pytest.fixture
def test_db() -> sqlite3.Connection:
    """Vytvoří in-memory databázi pro testy."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def create_prices_for_date(target_date: date, price_multiplier: float = 1.0) -> list[SpotPrice]:
    """Vytvoří ceny pro daný den s různými cenami podle hodiny."""
    prices = []
    for hour in range(24):
        for quarter in range(4):
            minute = quarter * 15
            time_from = datetime(
                target_date.year, target_date.month, target_date.day, hour, minute
            )
            time_to = datetime(
                target_date.year, target_date.month, target_date.day, hour, minute + 14, 59
            )
            # Cena podle hodiny: noc levná, ráno a večer drahé
            if 0 <= hour <= 5:
                base_price = 30.0  # Noc - levné
            elif 6 <= hour <= 9:
                base_price = 80.0  # Ráno - drahé
            elif 10 <= hour <= 16:
                base_price = 50.0  # Den - střední
            elif 17 <= hour <= 21:
                base_price = 90.0  # Večer - nejdražší
            else:
                base_price = 40.0  # Pozdní večer

            prices.append(SpotPrice(
                time_from=time_from,
                time_to=time_to,
                price_eur=base_price * price_multiplier,
                price_czk=base_price * price_multiplier * 25.0,
            ))
    return prices


@pytest.fixture
def populated_db(test_db: sqlite3.Connection) -> sqlite3.Connection:
    """Databáze s daty za 14 dnů."""
    today = date.today()
    for i in range(14):
        day = today - timedelta(days=i)
        prices = create_prices_for_date(day, price_multiplier=1.0 + (i % 3) * 0.1)
        save_prices(test_db, day, prices, 25.0)
    return test_db


def test_get_hourly_patterns(populated_db: sqlite3.Connection) -> None:
    """Test získání hodinových vzorců."""
    patterns = get_hourly_patterns(populated_db, days_back=14)

    assert len(patterns) == 24
    assert all(isinstance(p, HourlyPattern) for p in patterns)

    # Ověř že noční hodiny jsou levnější než denní
    night_pattern = next(p for p in patterns if p.hour == 2)
    evening_pattern = next(p for p in patterns if p.hour == 19)
    assert night_pattern.avg_price < evening_pattern.avg_price


def test_get_hourly_patterns_empty_db(test_db: sqlite3.Connection) -> None:
    """Test hodinových vzorců na prázdné databázi."""
    patterns = get_hourly_patterns(test_db, days_back=30)
    assert patterns == []


def test_get_best_hours(populated_db: sqlite3.Connection) -> None:
    """Test nejlevnějších hodin."""
    best = get_best_hours(populated_db, top_n=5)

    assert len(best) == 5
    # Ověř že jsou seřazené od nejlevnější
    prices = [price for _, price in best]
    assert prices == sorted(prices)

    # Noční hodiny by měly být mezi nejlevnějšími
    hours = [hour for hour, _ in best]
    assert any(0 <= h <= 5 for h in hours)


def test_get_worst_hours(populated_db: sqlite3.Connection) -> None:
    """Test nejdražších hodin."""
    worst = get_worst_hours(populated_db, top_n=5)

    assert len(worst) == 5
    # Ověř že jsou seřazené od nejdražší
    prices = [price for _, price in worst]
    assert prices == sorted(prices, reverse=True)

    # Večerní hodiny by měly být mezi nejdražšími
    hours = [hour for hour, _ in worst]
    assert any(17 <= h <= 21 for h in hours)


def test_get_best_hours_less_than_requested(test_db: sqlite3.Connection) -> None:
    """Test když je méně hodin než požadováno."""
    # Přidej data jen pro několik hodin
    today = date.today()
    prices = create_prices_for_date(today)[:8]  # Jen první 2 hodiny
    save_prices(test_db, today, prices, 25.0)

    best = get_best_hours(test_db, top_n=5)
    assert len(best) <= 5


def test_classify_price_very_cheap(populated_db: sqlite3.Connection) -> None:
    """Test klasifikace velmi levné ceny."""
    # Velmi nízká cena
    result = classify_price(100.0, populated_db, days_back=14)
    assert result == "velmi levná"


def test_classify_price_very_expensive(populated_db: sqlite3.Connection) -> None:
    """Test klasifikace velmi drahé ceny."""
    # Velmi vysoká cena
    result = classify_price(5000.0, populated_db, days_back=14)
    assert result == "velmi drahá"


def test_classify_price_normal(populated_db: sqlite3.Connection) -> None:
    """Test klasifikace normální ceny."""
    # Střední cena
    result = classify_price(1400.0, populated_db, days_back=14)
    assert result in ["levná", "normální", "drahá"]


def test_classify_price_insufficient_data(test_db: sqlite3.Connection) -> None:
    """Test klasifikace s nedostatkem dat."""
    result = classify_price(1000.0, test_db, days_back=30)
    assert result == "nedostatek dat"


def test_get_price_level_color() -> None:
    """Test barev pro cenové úrovně."""
    assert get_price_level_color("velmi levná") == "#28a745"
    assert get_price_level_color("levná") == "#7cb342"
    assert get_price_level_color("normální") == "#ffc107"
    assert get_price_level_color("drahá") == "#ff9800"
    assert get_price_level_color("velmi drahá") == "#dc3545"
    assert get_price_level_color("nedostatek dat") == "#6c757d"
    assert get_price_level_color("neznámá") == "#6c757d"


def test_get_weekday_hour_heatmap_data(populated_db: sqlite3.Connection) -> None:
    """Test dat pro týdenní heatmapu."""
    data = get_weekday_hour_heatmap_data(populated_db, days_back=14)

    assert len(data) > 0

    # Ověř strukturu
    for item in data:
        assert "weekday" in item
        assert "weekday_name" in item
        assert "hour" in item
        assert "avg_price" in item
        assert 0 <= item["weekday"] <= 6
        assert 0 <= item["hour"] <= 23
        assert item["weekday_name"] in ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"]


def test_get_weekday_hour_heatmap_data_empty(test_db: sqlite3.Connection) -> None:
    """Test heatmap dat na prázdné databázi."""
    data = get_weekday_hour_heatmap_data(test_db, days_back=30)
    assert data == []


def test_hourly_pattern_dataclass() -> None:
    """Test HourlyPattern dataclass."""
    pattern = HourlyPattern(
        hour=10,
        avg_price=1500.0,
        min_price=1200.0,
        max_price=1800.0,
        sample_count=100,
    )

    assert pattern.hour == 10
    assert pattern.avg_price == 1500.0
    assert pattern.min_price == 1200.0
    assert pattern.max_price == 1800.0
    assert pattern.sample_count == 100


# --- Tests for negative price analysis ---


def create_prices_with_negatives(target_date: date) -> list[SpotPrice]:
    """Vytvoří ceny pro daný den s několika negativními cenami."""
    prices = []
    for hour in range(24):
        for quarter in range(4):
            minute = quarter * 15
            time_from = datetime(
                target_date.year, target_date.month, target_date.day, hour, minute
            )
            time_to = datetime(
                target_date.year, target_date.month, target_date.day, hour, minute + 14, 59
            )
            # Negativní ceny v hodinách 2-4
            if 2 <= hour <= 4:
                base_price = -10.0
            else:
                base_price = 50.0

            prices.append(SpotPrice(
                time_from=time_from,
                time_to=time_to,
                price_eur=base_price,
                price_czk=base_price * 25.0,
            ))
    return prices


@pytest.fixture
def db_with_negatives(test_db: sqlite3.Connection) -> sqlite3.Connection:
    """Databáze s negativními cenami."""
    today = date.today()
    for i in range(10):
        day = today - timedelta(days=i)
        prices = create_prices_with_negatives(day)
        save_prices(test_db, day, prices, 25.0)
    return test_db


def test_get_negative_price_stats(db_with_negatives: sqlite3.Connection) -> None:
    """Test statistik negativních cen."""
    stats = get_negative_price_stats(db_with_negatives, days_back=30)

    assert isinstance(stats, NegativePriceStats)
    assert stats.count > 0
    assert stats.avg_negative_price is not None
    assert stats.avg_negative_price < 0
    assert stats.min_price is not None
    assert stats.min_price < 0
    assert isinstance(stats.hours_distribution, dict)
    # Hodiny 2, 3, 4 by měly být v distribuci
    hours_dist = stats.hours_distribution
    assert any(h in hours_dist for h in [2, 3, 4])


def test_get_negative_price_stats_no_negatives(populated_db: sqlite3.Connection) -> None:
    """Test statistik když nejsou negativní ceny."""
    stats = get_negative_price_stats(populated_db, days_back=30)

    assert isinstance(stats, NegativePriceStats)
    assert stats.count == 0
    assert stats.avg_negative_price is None
    assert stats.min_price is None
    assert stats.hours_distribution == {}


def test_get_negative_price_hours_list(db_with_negatives: sqlite3.Connection) -> None:
    """Test seznamu hodin s negativními cenami."""
    hours = get_negative_price_hours_list(db_with_negatives, days_back=30)

    assert len(hours) > 0
    for h in hours:
        assert h.date is not None
        assert h.hour is not None
        assert h.price_czk is not None
        assert h.price_czk <= 0


def test_get_negative_price_forecast(db_with_negatives: sqlite3.Connection) -> None:
    """Test predikce negativních cen."""
    risky_hours = get_negative_price_forecast(db_with_negatives)

    # Hodiny 2, 3, 4 mají negativní ceny každý den (10 dnů > 3 výskytů)
    assert 2 in risky_hours or 3 in risky_hours or 4 in risky_hours
    assert all(0 <= h <= 23 for h in risky_hours)


def test_get_negative_price_forecast_no_negatives(populated_db: sqlite3.Connection) -> None:
    """Test predikce když nejsou negativní ceny."""
    risky_hours = get_negative_price_forecast(populated_db)
    assert risky_hours == []


# --- Tests for trends and distribution ---


def test_get_price_distribution(populated_db: sqlite3.Connection) -> None:
    """Test distribuce cen."""
    dist = get_price_distribution(populated_db, days_back=14)

    assert isinstance(dist, PriceDistribution)
    assert len(dist.bins) > 0
    assert len(dist.counts) == len(dist.bins)
    assert "p10" in dist.percentiles
    assert "p25" in dist.percentiles
    assert "p50" in dist.percentiles
    assert "p75" in dist.percentiles
    assert "p90" in dist.percentiles

    # Percentily by měly být seřazené
    p = dist.percentiles
    assert p["p10"] <= p["p25"] <= p["p50"] <= p["p75"] <= p["p90"]


def test_get_price_distribution_empty(test_db: sqlite3.Connection) -> None:
    """Test distribuce na prázdné databázi."""
    dist = get_price_distribution(test_db, days_back=30)

    assert isinstance(dist, PriceDistribution)
    assert dist.bins == []
    assert dist.counts == []
    assert dist.percentiles == {}


def test_get_moving_averages(populated_db: sqlite3.Connection) -> None:
    """Test klouzavých průměrů."""
    ma = get_moving_averages(populated_db, days_back=14)

    assert len(ma) > 0
    for item in ma:
        assert isinstance(item, MovingAverageDay)
        assert item.date is not None
        assert item.daily_avg is not None

    # 7denní MA by měl být dostupný po 7 dnech
    items_with_ma7 = [i for i in ma if i.ma7 is not None]
    assert len(items_with_ma7) > 0


def test_get_moving_averages_empty(test_db: sqlite3.Connection) -> None:
    """Test klouzavých průměrů na prázdné databázi."""
    ma = get_moving_averages(test_db, days_back=30)
    assert ma == []


def test_get_price_trend(populated_db: sqlite3.Connection) -> None:
    """Test trendu cen."""
    trend = get_price_trend(populated_db, days_back=7)

    assert isinstance(trend, PriceTrend)
    assert trend.direction in ["rostoucí", "klesající", "stabilní", "nedostatek dat"]


def test_get_price_trend_insufficient_data(test_db: sqlite3.Connection) -> None:
    """Test trendu s nedostatkem dat."""
    trend = get_price_trend(test_db, days_back=30)

    assert isinstance(trend, PriceTrend)
    assert trend.direction == "nedostatek dat"
    assert trend.change_percent is None
