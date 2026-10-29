"""Testy pro model predikce spotu (bez sítě – syntetické ceny a počasí)."""

from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from ote.price_model import (
    build_features,
    cz_holidays,
    evaluate,
    fit_predict,
    forecast,
    future_slots,
    profile_predict,
)

START = date(2026, 9, 1)
DAYS = 50


def synthetic_weather(days: int = DAYS + 8) -> pd.DataFrame:
    rng = np.random.default_rng(1)
    times = pd.date_range(datetime.combine(START, datetime.min.time()), periods=days * 24,
                          freq="h")
    hour = times.hour.to_numpy()
    sun = np.clip(np.sin((hour - 6) / 12 * np.pi), 0, None)
    daily_sun = np.repeat(rng.uniform(0.2, 1.0, days), 24)
    return pd.DataFrame({
        "time": times,
        "temp": 10 + 5 * sun,
        "solar": 600 * sun * daily_sun,
        "wind": np.repeat(rng.uniform(5, 40, days), 24),
        "cloud": 100 * (1 - daily_sun),
        "wind_n": np.repeat(rng.uniform(5, 50, days), 24),
    })


def synthetic_prices(weather: pd.DataFrame, days: int = DAYS) -> pd.DataFrame:
    """Cena = denní profil − vliv slunce − vliv větru (model by to měl zachytit)."""
    slots = future_slots(START, days)
    f = build_features(slots, weather)
    profile = 3000 + 1500 * np.sin((f["slot"] - 28) / 96 * 2 * np.pi)
    price = profile - 4 * f["solar"] - 30 * f["wind_n"]
    return slots.assign(price_czk=price.to_numpy())


def test_cz_holidays_easter() -> None:
    holidays = cz_holidays(2026)
    assert date(2026, 4, 3) in holidays  # Velký pátek
    assert date(2026, 4, 6) in holidays  # Velikonoční pondělí
    assert date(2026, 10, 28) in holidays
    assert date(2026, 4, 5) not in holidays  # neděle není státní svátek


def test_build_features_columns() -> None:
    weather = synthetic_weather()
    f = build_features(future_slots(date(2026, 10, 28), 1), weather)
    assert len(f) == 96
    assert f["slot"].tolist() == list(range(96))
    assert f["holiday"].eq(1).all()
    assert f["solar"].notna().all()


def test_fit_predict_beats_profile() -> None:
    weather = synthetic_weather()
    f = build_features(synthetic_prices(weather), weather)
    train = f[f["day"] < START + timedelta(days=40)]
    train = train[train["day"] >= START + timedelta(days=10)]
    test = f[(f["day"] >= START + timedelta(days=40)) & (f["day"] < START + timedelta(days=46))]
    model_mae = np.abs(test["price_czk"] - fit_predict(train, test)).mean()
    profile_mae = np.abs(test["price_czk"] - profile_predict(train, test)).mean()
    assert model_mae < profile_mae


def test_forecast_horizon() -> None:
    weather = synthetic_weather()
    prices = synthetic_prices(weather)
    last_known = START + timedelta(days=DAYS - 1)
    result = forecast(prices, weather, last_known, last_known + timedelta(days=6))
    assert len(result) == 6 * 96
    assert sorted(result["h"].unique()) == [1, 2, 3, 4, 5, 6]
    assert forecast(prices, weather, last_known, last_known).empty


def test_evaluate_reports_per_horizon() -> None:
    weather = synthetic_weather()
    prices = synthetic_prices(weather)
    lagged = {lag: weather for lag in range(8)}
    ev = evaluate(prices, lagged, origins=3)
    assert ev is not None
    assert ev.origins == 3
    assert ev.by_horizon["h"].tolist() == [1, 2, 3, 4, 5, 6]
    assert ev.mae < ev.baseline_mae
    assert (ev.residual_quantiles["q10"] <= ev.residual_quantiles["q90"]).all()


def test_evaluate_needs_history() -> None:
    weather = synthetic_weather()
    prices = synthetic_prices(weather, days=20)
    assert evaluate(prices, {lag: weather for lag in range(8)}) is None


@pytest.mark.parametrize("year", [2025, 2026, 2027])
def test_holidays_count(year: int) -> None:
    assert len(cz_holidays(year)) == 13
