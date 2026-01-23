"""Modul pro integraci s meteorologickým API."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import httpx

# Open-Meteo API (zdarma, bez API klíče)
# https://open-meteo.com/
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# Souřadnice pro Českou republiku (Praha)
CZECH_COORDS = {"latitude": 50.08, "longitude": 14.43}


@dataclass
class WeatherData:
    """Meteorologická data pro konkrétní hodinu."""

    datetime: datetime
    temperature: float  # °C
    cloud_cover: int  # % (0-100)
    solar_radiation: float  # W/m² (direct + diffuse)
    wind_speed: float  # m/s
    precipitation: float  # mm


@dataclass
class WeatherForecast:
    """Předpověď počasí na den."""

    date: date
    hourly_data: list[WeatherData]
    avg_temperature: float
    avg_cloud_cover: float
    total_solar_radiation: float
    avg_wind_speed: float
    weather_type: str  # "sunny", "cloudy", "windy", "mixed"


@dataclass
class WeatherCorrelation:
    """Korelace počasí a cen."""

    temperature_correlation: float  # -1 až 1
    cloud_cover_correlation: float
    solar_radiation_correlation: float
    wind_speed_correlation: float
    strongest_factor: str
    r_squared: float  # vysvětlená variance


def get_weather_type(cloud_cover: float, wind_speed: float) -> str:
    """Určí typ počasí na základě oblačnosti a větru.

    Args:
        cloud_cover: Průměrná oblačnost (%).
        wind_speed: Průměrná rychlost větru (m/s).

    Returns:
        Typ počasí: "sunny", "cloudy", "windy", "mixed".
    """
    if cloud_cover < 30 and wind_speed < 6:
        return "sunny"
    elif wind_speed >= 8:
        return "windy"
    elif cloud_cover >= 70:
        return "cloudy"
    else:
        return "mixed"


def fetch_weather_forecast(days_ahead: int = 7) -> list[WeatherForecast]:
    """Načte předpověď počasí z Open-Meteo API.

    Args:
        days_ahead: Počet dnů dopředu (max 16).

    Returns:
        Seznam předpovědí pro každý den.
    """
    hourly_params = (
        "temperature_2m,cloud_cover,direct_radiation,"
        "diffuse_radiation,wind_speed_10m,precipitation"
    )
    params: dict[str, str | int | float] = {
        "latitude": CZECH_COORDS["latitude"],
        "longitude": CZECH_COORDS["longitude"],
        "hourly": hourly_params,
        "forecast_days": min(days_ahead, 16),
        "timezone": "Europe/Prague",
    }

    try:
        response = httpx.get(OPEN_METEO_URL, params=params, timeout=10.0)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        raise RuntimeError(f"Chyba při načítání počasí: {e}") from e

    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    temperatures = hourly.get("temperature_2m", [])
    cloud_covers = hourly.get("cloud_cover", [])
    direct_rad = hourly.get("direct_radiation", [])
    diffuse_rad = hourly.get("diffuse_radiation", [])
    wind_speeds = hourly.get("wind_speed_10m", [])
    precipitations = hourly.get("precipitation", [])

    # Seskup data podle dne
    daily_data: dict[date, list[WeatherData]] = {}

    for i, time_str in enumerate(times):
        dt = datetime.fromisoformat(time_str)
        d = dt.date()

        if d not in daily_data:
            daily_data[d] = []

        solar = (direct_rad[i] if i < len(direct_rad) else 0) + (
            diffuse_rad[i] if i < len(diffuse_rad) else 0
        )

        daily_data[d].append(
            WeatherData(
                datetime=dt,
                temperature=temperatures[i] if i < len(temperatures) else 0.0,
                cloud_cover=int(cloud_covers[i]) if i < len(cloud_covers) else 0,
                solar_radiation=solar,
                wind_speed=wind_speeds[i] if i < len(wind_speeds) else 0.0,
                precipitation=precipitations[i] if i < len(precipitations) else 0.0,
            )
        )

    # Vytvoř denní předpovědi
    forecasts: list[WeatherForecast] = []

    for d, hourly_list in sorted(daily_data.items()):
        if not hourly_list:
            continue

        avg_temp = sum(h.temperature for h in hourly_list) / len(hourly_list)
        avg_cloud = sum(h.cloud_cover for h in hourly_list) / len(hourly_list)
        total_solar = sum(h.solar_radiation for h in hourly_list)
        avg_wind = sum(h.wind_speed for h in hourly_list) / len(hourly_list)

        weather_type = get_weather_type(avg_cloud, avg_wind)

        forecasts.append(
            WeatherForecast(
                date=d,
                hourly_data=hourly_list,
                avg_temperature=avg_temp,
                avg_cloud_cover=avg_cloud,
                total_solar_radiation=total_solar,
                avg_wind_speed=avg_wind,
                weather_type=weather_type,
            )
        )

    return forecasts


def fetch_historical_weather(target_date: date) -> WeatherForecast | None:
    """Načte historická meteorologická data pro daný den.

    Args:
        target_date: Datum pro které chceme data.

    Returns:
        WeatherForecast nebo None pokud nejsou data.
    """
    # Open-Meteo historical API
    url = "https://archive-api.open-meteo.com/v1/archive"

    hourly_params = (
        "temperature_2m,cloud_cover,direct_radiation,"
        "diffuse_radiation,wind_speed_10m,precipitation"
    )
    params: dict[str, str | int | float] = {
        "latitude": CZECH_COORDS["latitude"],
        "longitude": CZECH_COORDS["longitude"],
        "start_date": target_date.isoformat(),
        "end_date": target_date.isoformat(),
        "hourly": hourly_params,
        "timezone": "Europe/Prague",
    }

    try:
        response = httpx.get(url, params=params, timeout=10.0)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, httpx.TimeoutException):
        return None

    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    temperatures = hourly.get("temperature_2m", [])
    cloud_covers = hourly.get("cloud_cover", [])
    direct_rad = hourly.get("direct_radiation", [])
    diffuse_rad = hourly.get("diffuse_radiation", [])
    wind_speeds = hourly.get("wind_speed_10m", [])
    precipitations = hourly.get("precipitation", [])

    if not times:
        return None

    hourly_list: list[WeatherData] = []

    for i, time_str in enumerate(times):
        dt = datetime.fromisoformat(time_str)

        solar = (direct_rad[i] if i < len(direct_rad) else 0) + (
            diffuse_rad[i] if i < len(diffuse_rad) else 0
        )

        hourly_list.append(
            WeatherData(
                datetime=dt,
                temperature=temperatures[i] if i < len(temperatures) else 0.0,
                cloud_cover=int(cloud_covers[i]) if i < len(cloud_covers) else 0,
                solar_radiation=solar,
                wind_speed=wind_speeds[i] if i < len(wind_speeds) else 0.0,
                precipitation=precipitations[i] if i < len(precipitations) else 0.0,
            )
        )

    if not hourly_list:
        return None

    avg_temp = sum(h.temperature for h in hourly_list) / len(hourly_list)
    avg_cloud = sum(h.cloud_cover for h in hourly_list) / len(hourly_list)
    total_solar = sum(h.solar_radiation for h in hourly_list)
    avg_wind = sum(h.wind_speed for h in hourly_list) / len(hourly_list)

    weather_type = get_weather_type(avg_cloud, avg_wind)

    return WeatherForecast(
        date=target_date,
        hourly_data=hourly_list,
        avg_temperature=avg_temp,
        avg_cloud_cover=avg_cloud,
        total_solar_radiation=total_solar,
        avg_wind_speed=avg_wind,
        weather_type=weather_type,
    )


def _calculate_correlation(x: list[float], y: list[float]) -> float:
    """Vypočítá Pearsonův korelační koeficient.

    Args:
        x: První řada hodnot.
        y: Druhá řada hodnot.

    Returns:
        Korelační koeficient (-1 až 1).
    """
    if len(x) != len(y) or len(x) < 3:
        return 0.0

    n = len(x)
    mean_x = sum(x) / n
    mean_y = sum(y) / n

    numerator = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
    sum_sq_x = sum((xi - mean_x) ** 2 for xi in x)
    sum_sq_y = sum((yi - mean_y) ** 2 for yi in y)

    denominator = (sum_sq_x * sum_sq_y) ** 0.5

    if denominator == 0:
        return 0.0

    return float(numerator / denominator)


def get_weather_price_correlation(
    conn: sqlite3.Connection,
    days_back: int = 30,
) -> WeatherCorrelation | None:
    """Vypočítá korelaci mezi počasím a cenami elektřiny.

    Args:
        conn: Databázové připojení.
        days_back: Počet dnů zpět pro analýzu.

    Returns:
        WeatherCorrelation nebo None pokud nejsou dostatečná data.
    """
    from ote.db import get_prices_for_range

    today = date.today()
    start_date = today - timedelta(days=days_back)

    # Získej ceny
    prices = get_prices_for_range(conn, start_date, today)

    if len(prices) < 48:  # Alespoň 2 dny dat
        return None

    # Získej historická meteorologická data
    weather_data: dict[datetime, WeatherData] = {}

    for day_offset in range(days_back):
        d = today - timedelta(days=day_offset)
        forecast = fetch_historical_weather(d)
        if forecast:
            for wd in forecast.hourly_data:
                weather_data[wd.datetime] = wd

    if len(weather_data) < 48:
        return None

    # Spáruj ceny s počasím
    temps: list[float] = []
    clouds: list[float] = []
    solars: list[float] = []
    winds: list[float] = []
    price_vals: list[float] = []

    for p in prices:
        # Najdi odpovídající počasí (zaokrouhleno na hodinu)
        hour_dt = p.time_from.replace(minute=0, second=0, microsecond=0)
        if hour_dt in weather_data:
            wd = weather_data[hour_dt]
            temps.append(wd.temperature)
            clouds.append(float(wd.cloud_cover))
            solars.append(wd.solar_radiation)
            winds.append(wd.wind_speed)
            price_vals.append(p.price_czk)

    if len(price_vals) < 24:
        return None

    # Vypočítej korelace
    temp_corr = _calculate_correlation(temps, price_vals)
    cloud_corr = _calculate_correlation(clouds, price_vals)
    solar_corr = _calculate_correlation(solars, price_vals)
    wind_corr = _calculate_correlation(winds, price_vals)

    # Najdi nejsilnější faktor
    correlations = {
        "teplota": abs(temp_corr),
        "oblačnost": abs(cloud_corr),
        "sluneční záření": abs(solar_corr),
        "vítr": abs(wind_corr),
    }
    strongest_factor = max(correlations, key=lambda k: correlations[k])

    # R-squared (vysvětlená variance) - použijeme nejsilnější korelaci
    r_squared = max(correlations.values()) ** 2

    return WeatherCorrelation(
        temperature_correlation=temp_corr,
        cloud_cover_correlation=cloud_corr,
        solar_radiation_correlation=solar_corr,
        wind_speed_correlation=wind_corr,
        strongest_factor=strongest_factor,
        r_squared=r_squared,
    )


def get_weather_adjustment_factor(weather: WeatherData) -> float:
    """Vypočítá korekční faktor pro cenu na základě počasí.

    Logika:
    - Slunečno (cloud < 30%) -> cena × 0.85 (fotovoltaika snižuje ceny)
    - Větrno (wind > 8 m/s) -> cena × 0.90 (vítr snižuje ceny)
    - Zataženo + bezvětří -> cena × 1.10 (vyšší ceny)
    - Extrémní teploty -> cena × 1.05 (topení/chlazení)

    Args:
        weather: Meteorologická data pro hodinu.

    Returns:
        Korekční faktor (0.8 - 1.2).
    """
    factor = 1.0

    # Sluneční záření - více slunce = nižší ceny
    if weather.cloud_cover < 30 and weather.solar_radiation > 300:
        factor *= 0.85
    elif weather.cloud_cover < 50:
        factor *= 0.92

    # Vítr - silný vítr = nižší ceny
    if weather.wind_speed >= 10:
        factor *= 0.88
    elif weather.wind_speed >= 8:
        factor *= 0.92

    # Zataženo bez větru = vyšší ceny
    if weather.cloud_cover >= 80 and weather.wind_speed < 4:
        factor *= 1.10

    # Extrémní teploty
    if weather.temperature < -5 or weather.temperature > 30:
        factor *= 1.05
    elif weather.temperature < 0 or weather.temperature > 25:
        factor *= 1.02

    # Omez rozsah
    return max(0.75, min(1.25, factor))


def forecast_weather_enhanced(
    conn: sqlite3.Connection,
    target_date: date,
    weather: WeatherForecast | None = None,
) -> list[tuple[int, float, float, float]]:
    """Vytvoří predikci cen s korekcí podle počasí.

    Kombinuje:
    1. Historické hodinové vzorce
    2. Den v týdnu
    3. Korekci podle počasí

    Args:
        conn: Databázové připojení.
        target_date: Cílové datum pro predikci.
        weather: Předpověď počasí nebo None (načte se automaticky).

    Returns:
        Seznam (hodina, predikovaná_cena, confidence_low, confidence_high).
    """
    from ote.db import get_hourly_aggregates, get_prices_for_range, get_weekday_aggregates

    # Získej počasí pokud není předáno
    if weather is None:
        forecasts = fetch_weather_forecast(days_ahead=7)
        weather = next((f for f in forecasts if f.date == target_date), None)

    weekday = target_date.weekday()

    # Získej vzorce pro den v týdnu
    weekday_aggregates = get_weekday_aggregates(conn, days_back=60)
    weekday_data = {
        agg["hour"]: agg for agg in weekday_aggregates if agg["weekday"] == weekday
    }

    # Fallback na hodinové průměry
    hourly_fallback = {agg["hour"]: agg for agg in get_hourly_aggregates(conn, 30)}

    # Historická std dev pro confidence intervaly
    today = date.today()
    start_date = today - timedelta(days=30)
    prices = get_prices_for_range(conn, start_date, today)

    hourly_prices: dict[int, list[float]] = {h: [] for h in range(24)}
    for p in prices:
        hourly_prices[p.time_from.hour].append(p.price_czk)

    # Počasí podle hodiny
    weather_by_hour: dict[int, WeatherData] = {}
    if weather:
        for wd in weather.hourly_data:
            weather_by_hour[wd.datetime.hour] = wd

    predictions: list[tuple[int, float, float, float]] = []

    for hour in range(24):
        data = weekday_data.get(hour) or hourly_fallback.get(hour)

        if not data:
            continue

        base_price = data["avg_price"]

        # Aplikuj weather adjustment
        if hour in weather_by_hour:
            adjustment = get_weather_adjustment_factor(weather_by_hour[hour])
            predicted_price = base_price * adjustment
        else:
            predicted_price = base_price

        # Confidence interval
        prices_for_hour = hourly_prices.get(hour, [])
        if len(prices_for_hour) >= 2:
            mean = sum(prices_for_hour) / len(prices_for_hour)
            variance = sum((p - mean) ** 2 for p in prices_for_hour) / len(prices_for_hour)
            std = variance**0.5
            confidence_low = max(0, predicted_price - 1.96 * std)
            confidence_high = predicted_price + 1.96 * std
        else:
            confidence_low = predicted_price * 0.7
            confidence_high = predicted_price * 1.3

        predictions.append((hour, predicted_price, confidence_low, confidence_high))

    return predictions
