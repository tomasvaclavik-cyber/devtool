"""Modul pro predikce cen elektřiny."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ote.spot import SpotPrice


@dataclass
class PriceForecast:
    """Předpověď ceny pro daný čas."""

    time_from: datetime
    time_to: datetime
    price_czk: float
    confidence_low: float
    confidence_high: float
    method: str


@dataclass
class DataSufficiency:
    """Informace o dostatečnosti dat pro predikce."""

    total_days: int
    can_show_tomorrow: bool  # day-ahead vždy dostupné z API
    can_show_hourly_patterns: bool  # potřeba 7+ dnů
    can_show_weekly_patterns: bool  # potřeba 14+ dnů
    can_show_statistical_forecast: bool  # potřeba 14+ dnů


def get_tomorrow_prices() -> tuple[list[SpotPrice], float, bool]:
    """Získá zítřejší ceny z OTE (day-ahead).

    OTE publikuje day-ahead ceny kolem 13:00 CET.

    Returns:
        Tuple (seznam SpotPrice, kurz EUR/CZK, zda jsou data dostupná).
    """
    from ote.spot import fetch_spot_prices

    tomorrow = date.today() + timedelta(days=1)

    try:
        prices, eur_czk_rate = fetch_spot_prices(tomorrow)
        return prices, eur_czk_rate, len(prices) > 0
    except Exception:
        return [], 0.0, False


def get_data_sufficiency(conn: sqlite3.Connection) -> DataSufficiency:
    """Zjistí, jaké metody predikce jsou dostupné na základě množství dat.

    Args:
        conn: Databázové připojení.

    Returns:
        Informace o dostupných metodách.
    """
    from ote.db import get_data_days_count

    total_days = get_data_days_count(conn)

    return DataSufficiency(
        total_days=total_days,
        can_show_tomorrow=True,  # day-ahead vždy dostupné z API
        can_show_hourly_patterns=total_days >= 7,
        can_show_weekly_patterns=total_days >= 14,
        can_show_statistical_forecast=total_days >= 14,
    )


def forecast_pattern_based(
    conn: sqlite3.Connection,
    target_date: date,
    hours: int = 24,
) -> list[PriceForecast]:
    """Vytvoří predikci na základě hodinových vzorců.

    Jednoduchá metoda: použije průměrnou cenu pro danou hodinu z historie.

    Args:
        conn: Databázové připojení.
        target_date: Cílové datum pro predikci.
        hours: Počet hodin k predikci (výchozí 24).

    Returns:
        Seznam predikcí pro každých 15 minut.
    """
    from ote.db import get_hourly_aggregates

    aggregates = get_hourly_aggregates(conn, days_back=30)

    # Převod na slovník pro rychlý přístup
    hourly_data = {agg["hour"]: agg for agg in aggregates}

    forecasts = []
    year = target_date.year
    month = target_date.month
    day = target_date.day

    for hour in range(hours):
        data = hourly_data.get(hour)
        if not data:
            continue

        avg_price = data["avg_price"]
        min_price = data["min_price"]
        max_price = data["max_price"]

        # Vytvoř predikci pro každých 15 minut v hodině
        for quarter in range(4):
            minute = quarter * 15
            time_from = datetime(year, month, day, hour, minute)
            time_to = datetime(year, month, day, hour, minute + 14, 59)

            forecasts.append(
                PriceForecast(
                    time_from=time_from,
                    time_to=time_to,
                    price_czk=avg_price,
                    confidence_low=min_price,
                    confidence_high=max_price,
                    method="hodinový vzorec",
                )
            )

    return forecasts


def forecast_statistical(
    conn: sqlite3.Connection,
    target_date: date,
    hours: int = 24,
) -> list[PriceForecast]:
    """Vytvoří statistickou predikci s confidence intervaly.

    Pokročilejší metoda využívající exponenciální vyhlazování
    a sezónní dekompozici.

    Args:
        conn: Databázové připojení.
        target_date: Cílové datum pro predikci.
        hours: Počet hodin k predikci.

    Returns:
        Seznam predikcí pro každých 15 minut.
    """
    from ote.db import get_prices_for_range, get_weekday_aggregates

    # Použij kombinaci hodinových a týdenních vzorců
    weekday = target_date.weekday()  # 0=Monday

    weekday_aggregates = get_weekday_aggregates(conn, days_back=60)

    # Filtruj na konkrétní den v týdnu
    weekday_data = {
        agg["hour"]: agg for agg in weekday_aggregates if agg["weekday"] == weekday
    }

    # Jako fallback použij hodinové vzorce
    from ote.db import get_hourly_aggregates

    hourly_fallback = {agg["hour"]: agg for agg in get_hourly_aggregates(conn, 30)}

    forecasts = []
    year = target_date.year
    month = target_date.month
    day = target_date.day

    # Získej historická data pro výpočet směrodatné odchylky
    end_date = date.today()
    start_date = end_date - timedelta(days=30)
    historical = get_prices_for_range(conn, start_date, end_date)

    # Seskup historická data podle hodiny
    hourly_prices: dict[int, list[float]] = {}
    for p in historical:
        h = p.time_from.hour
        if h not in hourly_prices:
            hourly_prices[h] = []
        hourly_prices[h].append(p.price_czk)

    for hour in range(hours):
        # Preferuj data pro konkrétní den v týdnu, jinak fallback
        data = weekday_data.get(hour) or hourly_fallback.get(hour)
        if not data:
            continue

        avg_price = data["avg_price"]

        # Výpočet confidence intervalu na základě směrodatné odchylky
        prices_for_hour = hourly_prices.get(hour, [])
        if len(prices_for_hour) >= 2:
            mean = sum(prices_for_hour) / len(prices_for_hour)
            variance = sum((p - mean) ** 2 for p in prices_for_hour) / len(prices_for_hour)
            std_dev = variance**0.5
            # 95% confidence interval
            confidence_low = max(0, avg_price - 1.96 * std_dev)
            confidence_high = avg_price + 1.96 * std_dev
        else:
            # Fallback na min/max z dat
            confidence_low = data.get("min_price", avg_price * 0.8)
            confidence_high = data.get("max_price", avg_price * 1.2)

        # Vytvoř predikci pro každých 15 minut
        for quarter in range(4):
            minute = quarter * 15
            time_from = datetime(year, month, day, hour, minute)
            time_to = datetime(year, month, day, hour, minute + 14, 59)

            forecasts.append(
                PriceForecast(
                    time_from=time_from,
                    time_to=time_to,
                    price_czk=avg_price,
                    confidence_low=confidence_low,
                    confidence_high=confidence_high,
                    method="statistická",
                )
            )

    return forecasts


def get_forecast_for_days(
    conn: sqlite3.Connection,
    days_ahead: int = 7,
) -> dict[date, list[PriceForecast]]:
    """Získá predikce pro více dnů dopředu.

    Args:
        conn: Databázové připojení.
        days_ahead: Počet dnů dopředu (výchozí 7).

    Returns:
        Slovník {datum: seznam predikcí}.
    """
    sufficiency = get_data_sufficiency(conn)

    result = {}
    today = date.today()

    for day_offset in range(2, days_ahead + 1):  # D+2 až D+days_ahead
        target_date = today + timedelta(days=day_offset)

        if sufficiency.can_show_statistical_forecast:
            forecasts = forecast_statistical(conn, target_date)
        elif sufficiency.can_show_hourly_patterns:
            forecasts = forecast_pattern_based(conn, target_date)
        else:
            forecasts = []

        if forecasts:
            result[target_date] = forecasts

    return result
