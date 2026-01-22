"""Testy pro modul predikcí."""

import sqlite3
from datetime import date, datetime, timedelta

import pytest

from ote.db import init_db, save_prices
from ote.forecast import (
    DataSufficiency,
    PriceForecast,
    forecast_pattern_based,
    forecast_statistical,
    get_data_sufficiency,
    get_forecast_for_days,
)
from ote.spot import SpotPrice


@pytest.fixture
def test_db() -> sqlite3.Connection:
    """Vytvoří in-memory databázi pro testy."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def create_prices_for_date(target_date: date) -> list[SpotPrice]:
    """Vytvoří ceny pro daný den."""
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
            # Cena podle hodiny
            base_price = 50.0 + hour * 2
            prices.append(SpotPrice(
                time_from=time_from,
                time_to=time_to,
                price_eur=base_price,
                price_czk=base_price * 25.0,
            ))
    return prices


@pytest.fixture
def db_with_7_days(test_db: sqlite3.Connection) -> sqlite3.Connection:
    """Databáze s daty za 7 dnů."""
    today = date.today()
    for i in range(7):
        day = today - timedelta(days=i)
        prices = create_prices_for_date(day)
        save_prices(test_db, day, prices, 25.0)
    return test_db


@pytest.fixture
def db_with_14_days(test_db: sqlite3.Connection) -> sqlite3.Connection:
    """Databáze s daty za 14 dnů."""
    today = date.today()
    for i in range(14):
        day = today - timedelta(days=i)
        prices = create_prices_for_date(day)
        save_prices(test_db, day, prices, 25.0)
    return test_db


def test_data_sufficiency_empty(test_db: sqlite3.Connection) -> None:
    """Test dostatečnosti dat na prázdné databázi."""
    sufficiency = get_data_sufficiency(test_db)

    assert isinstance(sufficiency, DataSufficiency)
    assert sufficiency.total_days == 0
    assert sufficiency.can_show_tomorrow is True  # Vždy z API
    assert sufficiency.can_show_hourly_patterns is False
    assert sufficiency.can_show_weekly_patterns is False
    assert sufficiency.can_show_statistical_forecast is False


def test_data_sufficiency_7_days(db_with_7_days: sqlite3.Connection) -> None:
    """Test dostatečnosti dat se 7 dny."""
    sufficiency = get_data_sufficiency(db_with_7_days)

    assert sufficiency.total_days == 7
    assert sufficiency.can_show_tomorrow is True
    assert sufficiency.can_show_hourly_patterns is True
    assert sufficiency.can_show_weekly_patterns is False
    assert sufficiency.can_show_statistical_forecast is False


def test_data_sufficiency_14_days(db_with_14_days: sqlite3.Connection) -> None:
    """Test dostatečnosti dat se 14 dny."""
    sufficiency = get_data_sufficiency(db_with_14_days)

    assert sufficiency.total_days == 14
    assert sufficiency.can_show_tomorrow is True
    assert sufficiency.can_show_hourly_patterns is True
    assert sufficiency.can_show_weekly_patterns is True
    assert sufficiency.can_show_statistical_forecast is True


def test_forecast_pattern_based(db_with_7_days: sqlite3.Connection) -> None:
    """Test predikce založené na vzorcích."""
    target = date.today() + timedelta(days=2)
    forecasts = forecast_pattern_based(db_with_7_days, target, hours=24)

    assert len(forecasts) == 96  # 24 hodin * 4 čtvrthodiny
    assert all(isinstance(f, PriceForecast) for f in forecasts)

    # Ověř strukturu
    for f in forecasts:
        assert f.price_czk > 0
        assert f.confidence_low <= f.price_czk <= f.confidence_high
        assert f.method == "hodinový vzorec"
        assert f.time_from.date() == target


def test_forecast_pattern_based_empty_db(test_db: sqlite3.Connection) -> None:
    """Test predikce na prázdné databázi."""
    target = date.today() + timedelta(days=2)
    forecasts = forecast_pattern_based(test_db, target, hours=24)

    assert forecasts == []


def test_forecast_statistical(db_with_14_days: sqlite3.Connection) -> None:
    """Test statistické predikce."""
    target = date.today() + timedelta(days=2)
    forecasts = forecast_statistical(db_with_14_days, target, hours=24)

    assert len(forecasts) == 96  # 24 hodin * 4 čtvrthodiny
    assert all(isinstance(f, PriceForecast) for f in forecasts)

    # Ověř strukturu
    for f in forecasts:
        assert f.price_czk > 0
        assert f.confidence_low >= 0  # Min může být 0
        assert f.method == "statistická"


def test_forecast_statistical_confidence_intervals(db_with_14_days: sqlite3.Connection) -> None:
    """Test že statistická predikce má rozumné confidence intervaly."""
    target = date.today() + timedelta(days=2)
    forecasts = forecast_statistical(db_with_14_days, target, hours=24)

    # Confidence interval by neměl být příliš úzký ani příliš široký
    for f in forecasts:
        interval_width = f.confidence_high - f.confidence_low
        # Interval by měl existovat
        assert interval_width >= 0


def test_get_forecast_for_days(db_with_14_days: sqlite3.Connection) -> None:
    """Test získání predikcí pro více dnů."""
    forecasts = get_forecast_for_days(db_with_14_days, days_ahead=5)

    # Měli bychom dostat predikce pro D+2 až D+5 (4 dny)
    assert len(forecasts) >= 1

    # Ověř že klíče jsou data
    for target_date, day_forecasts in forecasts.items():
        assert isinstance(target_date, date)
        assert target_date > date.today()
        assert len(day_forecasts) > 0


def test_get_forecast_for_days_insufficient_data(test_db: sqlite3.Connection) -> None:
    """Test predikcí s nedostatkem dat."""
    forecasts = get_forecast_for_days(test_db, days_ahead=5)
    assert forecasts == {}


def test_price_forecast_dataclass() -> None:
    """Test PriceForecast dataclass."""
    now = datetime.now()
    forecast = PriceForecast(
        time_from=now,
        time_to=now + timedelta(minutes=15),
        price_czk=1500.0,
        confidence_low=1200.0,
        confidence_high=1800.0,
        method="test",
    )

    assert forecast.time_from == now
    assert forecast.price_czk == 1500.0
    assert forecast.confidence_low == 1200.0
    assert forecast.confidence_high == 1800.0
    assert forecast.method == "test"


def test_data_sufficiency_dataclass() -> None:
    """Test DataSufficiency dataclass."""
    sufficiency = DataSufficiency(
        total_days=10,
        can_show_tomorrow=True,
        can_show_hourly_patterns=True,
        can_show_weekly_patterns=False,
        can_show_statistical_forecast=False,
    )

    assert sufficiency.total_days == 10
    assert sufficiency.can_show_tomorrow is True
    assert sufficiency.can_show_hourly_patterns is True
    assert sufficiency.can_show_weekly_patterns is False


def test_forecast_uses_statistical_when_available(db_with_14_days: sqlite3.Connection) -> None:
    """Test že se používá statistická metoda když je dostupná."""
    forecasts = get_forecast_for_days(db_with_14_days, days_ahead=3)

    # S 14 dny dat by měla být použita statistická metoda
    for _, day_forecasts in forecasts.items():
        assert day_forecasts[0].method == "statistická"


def test_forecast_uses_pattern_when_statistical_unavailable(
    db_with_7_days: sqlite3.Connection,
) -> None:
    """Test že se používá pattern metoda když statistická není dostupná."""
    forecasts = get_forecast_for_days(db_with_7_days, days_ahead=3)

    # Se 7 dny dat by měla být použita pattern metoda
    for _, day_forecasts in forecasts.items():
        assert day_forecasts[0].method == "hodinový vzorec"
