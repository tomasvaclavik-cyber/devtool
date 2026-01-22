"""Testy pro databázový modul."""

import sqlite3
from datetime import date, datetime, timedelta

import pytest

from ote.db import (
    get_available_dates,
    get_daily_stats,
    get_data_days_count,
    get_hourly_aggregates,
    get_overall_stats,
    get_prices_for_date,
    get_prices_for_range,
    get_weekday_aggregates,
    init_db,
    save_prices,
)
from ote.spot import SpotPrice


@pytest.fixture
def test_db() -> sqlite3.Connection:
    """Vytvoří in-memory databázi pro testy."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


@pytest.fixture
def sample_prices() -> list[SpotPrice]:
    """Vytvoří ukázkové ceny pro testy."""
    base_date = date.today()
    prices = []
    for hour in range(24):
        for quarter in range(4):
            minute = quarter * 15
            time_from = datetime(
                base_date.year, base_date.month, base_date.day, hour, minute
            )
            time_to = datetime(
                base_date.year, base_date.month, base_date.day, hour, minute + 14, 59
            )
            # Cena variuje podle hodiny - dražší ráno a večer
            base_price = 50.0 + (10.0 if 7 <= hour <= 9 or 17 <= hour <= 20 else 0)
            prices.append(SpotPrice(
                time_from=time_from,
                time_to=time_to,
                price_eur=base_price,
                price_czk=base_price * 25.0,
            ))
    return prices


def test_init_db(test_db: sqlite3.Connection) -> None:
    """Test inicializace databáze."""
    cursor = test_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='spot_prices'"
    )
    assert cursor.fetchone() is not None


def test_save_and_get_prices(test_db: sqlite3.Connection, sample_prices: list[SpotPrice]) -> None:
    """Test uložení a načtení cen."""
    report_date = date.today()
    count = save_prices(test_db, report_date, sample_prices, 25.0)
    assert count == len(sample_prices)

    loaded = get_prices_for_date(test_db, report_date)
    assert len(loaded) == len(sample_prices)
    assert loaded[0].price_eur == sample_prices[0].price_eur


def test_get_available_dates(test_db: sqlite3.Connection, sample_prices: list[SpotPrice]) -> None:
    """Test získání dostupných dat."""
    today = date.today()
    yesterday = today - timedelta(days=1)

    save_prices(test_db, today, sample_prices, 25.0)
    save_prices(test_db, yesterday, sample_prices, 25.0)

    dates = get_available_dates(test_db)
    assert len(dates) == 2
    assert today in dates
    assert yesterday in dates


def test_get_daily_stats(test_db: sqlite3.Connection, sample_prices: list[SpotPrice]) -> None:
    """Test denních statistik."""
    report_date = date.today()
    save_prices(test_db, report_date, sample_prices, 25.0)

    stats = get_daily_stats(test_db, report_date)
    assert stats is not None
    assert "min" in stats
    assert "max" in stats
    assert "avg" in stats
    assert stats["min"] <= stats["avg"] <= stats["max"]


def test_get_daily_stats_empty(test_db: sqlite3.Connection) -> None:
    """Test denních statistik pro prázdnou databázi."""
    stats = get_daily_stats(test_db, date.today())
    assert stats is None


def test_get_prices_for_range(test_db: sqlite3.Connection, sample_prices: list[SpotPrice]) -> None:
    """Test načtení cen pro rozsah dat."""
    today = date.today()
    yesterday = today - timedelta(days=1)

    save_prices(test_db, today, sample_prices, 25.0)
    save_prices(test_db, yesterday, sample_prices, 25.0)

    # Načti oba dny
    prices = get_prices_for_range(test_db, yesterday, today)
    assert len(prices) == len(sample_prices) * 2

    # Načti jen jeden den
    prices_one = get_prices_for_range(test_db, today, today)
    assert len(prices_one) == len(sample_prices)


def test_get_hourly_aggregates(test_db: sqlite3.Connection, sample_prices: list[SpotPrice]) -> None:
    """Test hodinových agregací."""
    today = date.today()
    save_prices(test_db, today, sample_prices, 25.0)

    aggregates = get_hourly_aggregates(test_db, days_back=1)
    assert len(aggregates) == 24  # 24 hodin

    # Ověř strukturu
    for agg in aggregates:
        assert "hour" in agg
        assert "avg_price" in agg
        assert "min_price" in agg
        assert "max_price" in agg
        assert 0 <= agg["hour"] <= 23


def test_get_weekday_aggregates(
    test_db: sqlite3.Connection, sample_prices: list[SpotPrice]
) -> None:
    """Test týdenních agregací."""
    today = date.today()
    save_prices(test_db, today, sample_prices, 25.0)

    aggregates = get_weekday_aggregates(test_db, days_back=1)
    assert len(aggregates) > 0

    for agg in aggregates:
        assert "weekday" in agg
        assert "hour" in agg
        assert "avg_price" in agg
        assert 0 <= agg["weekday"] <= 6


def test_get_data_days_count(test_db: sqlite3.Connection, sample_prices: list[SpotPrice]) -> None:
    """Test počtu dnů s daty."""
    assert get_data_days_count(test_db) == 0

    today = date.today()
    save_prices(test_db, today, sample_prices, 25.0)
    assert get_data_days_count(test_db) == 1

    yesterday = today - timedelta(days=1)
    save_prices(test_db, yesterday, sample_prices, 25.0)
    assert get_data_days_count(test_db) == 2


def test_get_overall_stats(test_db: sqlite3.Connection, sample_prices: list[SpotPrice]) -> None:
    """Test celkových statistik."""
    today = date.today()
    save_prices(test_db, today, sample_prices, 25.0)

    stats = get_overall_stats(test_db, days_back=1)
    assert stats is not None
    assert "avg" in stats
    assert "min" in stats
    assert "max" in stats
    assert stats["count"] > 0


def test_get_overall_stats_empty(test_db: sqlite3.Connection) -> None:
    """Test celkových statistik pro prázdnou databázi."""
    stats = get_overall_stats(test_db, days_back=1)
    assert stats is None


def test_save_prices_upsert(test_db: sqlite3.Connection, sample_prices: list[SpotPrice]) -> None:
    """Test že upsert přepíše existující záznamy."""
    report_date = date.today()

    # První uložení
    save_prices(test_db, report_date, sample_prices, 25.0)

    # Druhé uložení se stejným datem
    modified_prices = [
        SpotPrice(
            time_from=p.time_from,
            time_to=p.time_to,
            price_eur=p.price_eur * 2,
            price_czk=p.price_czk * 2,
        )
        for p in sample_prices
    ]
    save_prices(test_db, report_date, modified_prices, 25.0)

    # Ověř že máme stále stejný počet záznamů
    loaded = get_prices_for_date(test_db, report_date)
    assert len(loaded) == len(sample_prices)

    # Ověř že ceny jsou aktualizované
    assert loaded[0].price_eur == sample_prices[0].price_eur * 2
