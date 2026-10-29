"""Predikce spotové ceny na 1–6 dní dopředu modelem s počasím a jeho vyhodnocení.

Model: gradient boosting (scikit-learn HistGradientBoostingRegressor, MAE ztráta) natrénovaný
na posledních 30 dnech po 15 minutách. Vstupy: čtvrthodina dne, den v týdnu, český svátek
a počasí zprůměrované přes body v ČR a Německu (sluneční záření, vítr ve 100 m, teplota,
oblačnost). Cílem je odchylka od průměrné ceny posledních 7 dní, takže predikce drží aktuální
cenovou hladinu. Starší dny mají menší váhu (poločas 10 dní).

Vyhodnocení je poctivý backtest: pro každý výchozí den se model natrénuje jen na datech,
která byla tehdy známá, a počasí pro predikované dny se bere z tehdejší předpovědi
(Open-Meteo Previous Runs API), ne ze skutečnosti.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import httpx
import numpy as np
import pandas as pd

TRAIN_DAYS = 30
LEVEL_DAYS = 7
HALF_LIFE_DAYS = 10
MAX_HORIZON = 6
SLOTS_PER_DAY = 96

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"

# Body pro počasí: ČR + Německo (cenu spoluurčuje FVE na jihu a vítr na severu)
WEATHER_POINTS = [
    (50.08, 14.42),  # Praha
    (49.94, 18.00),  # Kravaře
    (49.20, 16.61),  # Brno
    (53.55, 9.99),  # Hamburk
    (52.52, 13.40),  # Berlín
    (51.31, 9.48),  # Kassel
    (48.14, 11.58),  # Mnichov
    (48.78, 9.18),  # Stuttgart
]
NORTH_POINTS = (3, 4)  # indexy bodů pro vítr na severu Německa
WEATHER_VARS = {
    "temperature_2m": "temp",
    "shortwave_radiation": "solar",
    "wind_speed_100m": "wind",
    "cloud_cover": "cloud",
}
FEATURES = ["slot", "dow", "holiday", "temp", "solar", "wind", "wind_n", "cloud"]


@dataclass
class Evaluation:
    """Výsledek backtestu."""

    origins: int  # počet výchozích dnů
    mae: float  # CZK/MWh, model
    baseline_mae: float  # CZK/MWh, průměrový profil posledních 30 dní
    bias: float  # průměr (skutečnost − predikce)
    daily_mae: float  # chyba průměrné ceny dne
    by_horizon: pd.DataFrame  # h, model_mae, baseline_mae
    residual_quantiles: pd.DataFrame  # h, q10, q90 (skutečnost − predikce)
    last_run: pd.DataFrame  # time_from, actual, predicted – nejnovější úplný backtest


def cz_holidays(year: int) -> set[date]:
    """České státní svátky (včetně Velkého pátku a Velikonočního pondělí)."""
    fixed = [(1, 1), (5, 1), (5, 8), (7, 5), (7, 6), (9, 28), (10, 28), (11, 17),
             (12, 24), (12, 25), (12, 26)]
    # Velikonoční neděle – anonymní gregoriánský algoritmus
    a, b, c = year % 19, year // 100, year % 100
    d, e = divmod(b, 4)
    g = (b - (b + 8) // 25 + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    weekday_shift = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * weekday_shift) // 451
    month, day = divmod(h + weekday_shift - 7 * m + 114, 31)
    easter = date(year, month, day + 1)
    return {date(year, mo, dd) for mo, dd in fixed} | {
        easter - timedelta(days=2), easter + timedelta(days=1),
    }


def _aggregate_weather(rows: pd.DataFrame) -> pd.DataFrame:
    """Průměr přes body + vítr na severu; řádky: time, loc, temp, solar, wind, cloud."""
    north = rows[rows["loc"].isin(NORTH_POINTS)].groupby("time")["wind"].mean().rename("wind_n")
    agg = rows.groupby("time")[list(WEATHER_VARS.values())].mean().join(north)
    return agg.reset_index()


def _get_locations(url: str, params: dict[str, str | int]) -> list[dict]:
    query = {
        "latitude": ",".join(str(p[0]) for p in WEATHER_POINTS),
        "longitude": ",".join(str(p[1]) for p in WEATHER_POINTS),
        "timezone": "Europe/Prague",
        **params,
    }
    response = httpx.get(url, params=query, timeout=60.0)
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, list) else [data]


def _hourly_frame(locations: list[dict], columns: dict[str, str]) -> pd.DataFrame:
    frames = []
    for i, loc in enumerate(locations):
        hourly = pd.DataFrame(loc["hourly"])
        frame = hourly[["time", *columns]].rename(columns=columns)
        frame["loc"] = i
        frames.append(frame)
    rows = pd.concat(frames, ignore_index=True)
    rows["time"] = pd.to_datetime(rows["time"])
    # Při změně času Open-Meteo opakuje hodinu – ceny v DB mají jen první výskyt
    rows = rows.drop_duplicates(subset=["time", "loc"])
    return _aggregate_weather(rows)


def fetch_weather(past_days: int = TRAIN_DAYS + 2, forecast_days: int = 8) -> pd.DataFrame:
    """Hodinové počasí: minulé dny (analýza) + předpověď dopředu."""
    locations = _get_locations(FORECAST_URL, {
        "hourly": ",".join(WEATHER_VARS), "past_days": past_days,
        "forecast_days": forecast_days,
    })
    return _hourly_frame(locations, WEATHER_VARS)


def fetch_weather_lagged(past_days: int = 60) -> dict[int, pd.DataFrame]:
    """Počasí tak, jak ho předpovídal model před `lag` dny (0 = analýza, 1–7 = předpověď)."""
    hourly = [f"{v}_previous_day{lag}" if lag else v for v in WEATHER_VARS for lag in range(8)]
    locations = _get_locations(PREVIOUS_RUNS_URL, {
        "hourly": ",".join(hourly), "past_days": past_days, "forecast_days": 1,
    })
    return {
        lag: _hourly_frame(locations, {
            (f"{v}_previous_day{lag}" if lag else v): name for v, name in WEATHER_VARS.items()
        })
        for lag in range(8)
    }


def build_features(slots: pd.DataFrame, weather: pd.DataFrame) -> pd.DataFrame:
    """K čtvrthodinám (sloupec time_from, volitelně price_czk) doplní vstupy modelu."""
    out = slots.copy()
    out["time_from"] = pd.to_datetime(out["time_from"])
    out["day"] = out["time_from"].dt.date
    out["hour_ts"] = out["time_from"].dt.floor("h")
    out = out.merge(weather.rename(columns={"time": "hour_ts"}), on="hour_ts", how="left")
    out["slot"] = out["time_from"].dt.hour * 4 + out["time_from"].dt.minute // 15
    out["dow"] = out["time_from"].dt.weekday
    years = {d.year for d in out["day"]}
    holidays = set().union(*(cz_holidays(y) for y in years)) if years else set()
    out["holiday"] = out["day"].isin(holidays).astype(int)
    return out.drop(columns="hour_ts")


def _daily_level(train: pd.DataFrame) -> tuple[dict[date, float], float]:
    """Úroveň = průměr posledních 7 dní před daným dnem; a úroveň k poslednímu dni."""
    daily = train.groupby("day")["price_czk"].mean()
    levels = {
        d: daily[(daily.index < d) & (daily.index >= d - timedelta(days=LEVEL_DAYS))].mean()
        for d in daily.index
    }
    last = daily.index.max()
    current = daily[daily.index > last - timedelta(days=LEVEL_DAYS)].mean()
    return levels, float(current)


def fit_predict(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    """Natrénuje model na `train` (s price_czk) a vrátí predikci pro řádky `test`."""
    from sklearn.ensemble import HistGradientBoostingRegressor
    from threadpoolctl import threadpool_limits

    levels, current_level = _daily_level(train)
    train = train.assign(level=train["day"].map(levels)).dropna(subset=["level", "solar"])
    origin = train["day"].max()
    age = np.array([(origin - d).days for d in train["day"]], dtype=float)
    weights = 0.5 ** (age / HALF_LIFE_DAYS)

    model = HistGradientBoostingRegressor(
        loss="absolute_error", max_iter=300, learning_rate=0.05, max_leaf_nodes=15,
        min_samples_leaf=20, random_state=0,
        categorical_features=[f in ("dow", "holiday") for f in FEATURES],
    )
    # Na Streamlit Cloudu je málo jader – víc vláken trénink spíš zpomalí
    with threadpool_limits(2):
        model.fit(train[FEATURES], train["price_czk"] - train["level"], sample_weight=weights)
        return model.predict(test[FEATURES]) + current_level


def profile_predict(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    """Srovnávací model: průměr stejné čtvrthodiny za 30 dní (zvlášť všední den/víkend)."""
    def daytype(frame: pd.DataFrame) -> pd.Series:
        return np.where((frame["dow"] >= 5) | (frame["holiday"] == 1), 1, 0)

    profile = train.assign(dt=daytype(train)).groupby(["dt", "slot"])["price_czk"].mean()
    overall = train.groupby("slot")["price_czk"].mean()
    return np.array([
        profile.get((dt, slot), overall.get(slot, np.nan))
        for dt, slot in zip(daytype(test), test["slot"])
    ])


def future_slots(start_day: date, days: int) -> pd.DataFrame:
    """Čtvrthodiny pro dny start_day … start_day + days − 1."""
    start = datetime.combine(start_day, datetime.min.time())
    return pd.DataFrame({
        "time_from": [start + timedelta(minutes=15 * i) for i in range(days * SLOTS_PER_DAY)],
    })


def forecast(
    prices: pd.DataFrame, weather: pd.DataFrame, last_known: date, until: date,
) -> pd.DataFrame:
    """Predikce pro dny po `last_known` až `until` (včetně).

    prices: time_from, price_czk (alespoň posledních 30 dní do `last_known`).
    Vrací time_from, predicted, h (horizont ve dnech od last_known).
    """
    days = (until - last_known).days
    if days <= 0:
        return pd.DataFrame(columns=["time_from", "predicted", "h"])
    features = build_features(prices, weather)
    train = features[(features["day"] > last_known - timedelta(days=TRAIN_DAYS))
                     & (features["day"] <= last_known)]
    test = build_features(future_slots(last_known + timedelta(days=1), days), weather)
    test = test.dropna(subset=["solar"])
    return pd.DataFrame({
        "time_from": test["time_from"].to_numpy(),
        "predicted": fit_predict(train, test),
        "h": [(d - last_known).days for d in test["day"]],
    })


def evaluate(
    prices: pd.DataFrame, lagged: dict[int, pd.DataFrame], origins: int = 14,
) -> Evaluation | None:
    """Backtest: posledních `origins` výchozích dnů, každý s predikcí na 1–6 dní."""
    analysis = build_features(prices, lagged[0])
    lagged_features = {lag: build_features(prices, w) for lag, w in lagged.items()}
    days = sorted(analysis["day"].unique())
    if len(days) < TRAIN_DAYS + MAX_HORIZON + 1:
        return None
    last_day = days[-1]
    candidates = [d for d in days
                  if days[0] + timedelta(days=TRAIN_DAYS) <= d
                  <= last_day - timedelta(days=MAX_HORIZON)]
    runs = []
    for origin in candidates[-origins:]:
        train = analysis[(analysis["day"] > origin - timedelta(days=TRAIN_DAYS))
                         & (analysis["day"] <= origin)]
        parts = []
        for h in range(1, MAX_HORIZON + 1):
            target = origin + timedelta(days=h)
            # Ceny originu vycházejí den předem, takže počasí je předpověď o den starší
            src = lagged_features[min(h + 1, 7)]
            parts.append(src[src["day"] == target].assign(h=h))
        test = pd.concat(parts).dropna(subset=["solar", "price_czk"])
        if test.empty:
            continue
        runs.append(test.assign(
            origin=origin, predicted=fit_predict(train, test),
            baseline=profile_predict(train, test),
        ))
    if not runs:
        return None
    res = pd.concat(runs, ignore_index=True)
    res["err"] = res["price_czk"] - res["predicted"]
    res["ae"] = res["err"].abs()
    res["base_ae"] = (res["price_czk"] - res["baseline"]).abs()
    by_h = res.groupby("h").agg(model_mae=("ae", "mean"), baseline_mae=("base_ae", "mean"))
    quantiles = res.groupby("h")["err"].quantile([0.1, 0.9]).unstack()
    quantiles.columns = ["q10", "q90"]
    daily_err = res.groupby(["origin", "day"])["err"].mean().abs()
    last_origin = res["origin"].max()
    last = res[res["origin"] == last_origin]
    return Evaluation(
        origins=res["origin"].nunique(),
        mae=float(res["ae"].mean()),
        baseline_mae=float(res["base_ae"].mean()),
        bias=float(res["err"].mean()),
        daily_mae=float(daily_err.mean()),
        by_horizon=by_h.reset_index(),
        residual_quantiles=quantiles.reset_index(),
        last_run=last[["time_from", "price_czk", "predicted", "h"]].rename(
            columns={"price_czk": "actual"}).reset_index(drop=True),
    )
