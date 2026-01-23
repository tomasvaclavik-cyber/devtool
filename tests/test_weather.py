"""Testy pro modul počasí."""

from datetime import date, datetime

from ote.weather import (
    WeatherCorrelation,
    WeatherData,
    WeatherForecast,
    get_weather_adjustment_factor,
    get_weather_type,
)


def test_get_weather_type_sunny() -> None:
    """Test detekce slunečného počasí."""
    assert get_weather_type(cloud_cover=20, wind_speed=3) == "sunny"
    assert get_weather_type(cloud_cover=10, wind_speed=5) == "sunny"


def test_get_weather_type_cloudy() -> None:
    """Test detekce zataženého počasí."""
    assert get_weather_type(cloud_cover=80, wind_speed=3) == "cloudy"
    assert get_weather_type(cloud_cover=90, wind_speed=5) == "cloudy"


def test_get_weather_type_windy() -> None:
    """Test detekce větrného počasí."""
    assert get_weather_type(cloud_cover=50, wind_speed=10) == "windy"
    assert get_weather_type(cloud_cover=20, wind_speed=12) == "windy"


def test_get_weather_type_mixed() -> None:
    """Test detekce proměnlivého počasí."""
    assert get_weather_type(cloud_cover=50, wind_speed=5) == "mixed"
    assert get_weather_type(cloud_cover=40, wind_speed=6) == "mixed"


def test_weather_data_dataclass() -> None:
    """Test WeatherData dataclass."""
    dt = datetime(2026, 1, 23, 12, 0)
    data = WeatherData(
        datetime=dt,
        temperature=10.5,
        cloud_cover=30,
        solar_radiation=450.0,
        wind_speed=5.0,
        precipitation=0.0,
    )

    assert data.datetime == dt
    assert data.temperature == 10.5
    assert data.cloud_cover == 30
    assert data.solar_radiation == 450.0
    assert data.wind_speed == 5.0
    assert data.precipitation == 0.0


def test_weather_forecast_dataclass() -> None:
    """Test WeatherForecast dataclass."""
    d = date(2026, 1, 23)
    hourly = [
        WeatherData(
            datetime=datetime(2026, 1, 23, h, 0),
            temperature=10.0 + h * 0.5,
            cloud_cover=20,
            solar_radiation=300.0,
            wind_speed=4.0,
            precipitation=0.0,
        )
        for h in range(24)
    ]

    forecast = WeatherForecast(
        date=d,
        hourly_data=hourly,
        avg_temperature=15.0,
        avg_cloud_cover=20.0,
        total_solar_radiation=7200.0,
        avg_wind_speed=4.0,
        weather_type="sunny",
    )

    assert forecast.date == d
    assert len(forecast.hourly_data) == 24
    assert forecast.avg_temperature == 15.0
    assert forecast.weather_type == "sunny"


def test_weather_correlation_dataclass() -> None:
    """Test WeatherCorrelation dataclass."""
    corr = WeatherCorrelation(
        temperature_correlation=0.15,
        cloud_cover_correlation=0.35,
        solar_radiation_correlation=-0.45,
        wind_speed_correlation=-0.30,
        strongest_factor="sluneční záření",
        r_squared=0.20,
    )

    assert corr.temperature_correlation == 0.15
    assert corr.solar_radiation_correlation == -0.45
    assert corr.strongest_factor == "sluneční záření"
    assert corr.r_squared == 0.20


def test_get_weather_adjustment_factor_sunny() -> None:
    """Test korekčního faktoru pro slunečno."""
    sunny = WeatherData(
        datetime=datetime(2026, 1, 23, 12, 0),
        temperature=15.0,
        cloud_cover=20,
        solar_radiation=500.0,
        wind_speed=3.0,
        precipitation=0.0,
    )

    factor = get_weather_adjustment_factor(sunny)
    assert factor < 1.0  # Slunečno = nižší ceny


def test_get_weather_adjustment_factor_windy() -> None:
    """Test korekčního faktoru pro větrno."""
    windy = WeatherData(
        datetime=datetime(2026, 1, 23, 12, 0),
        temperature=10.0,
        cloud_cover=50,
        solar_radiation=200.0,
        wind_speed=12.0,
        precipitation=0.0,
    )

    factor = get_weather_adjustment_factor(windy)
    assert factor < 1.0  # Větrno = nižší ceny


def test_get_weather_adjustment_factor_cloudy_calm() -> None:
    """Test korekčního faktoru pro zataženo bez větru."""
    cloudy = WeatherData(
        datetime=datetime(2026, 1, 23, 12, 0),
        temperature=10.0,
        cloud_cover=90,
        solar_radiation=50.0,
        wind_speed=2.0,
        precipitation=0.0,
    )

    factor = get_weather_adjustment_factor(cloudy)
    assert factor > 1.0  # Zataženo bez větru = vyšší ceny


def test_get_weather_adjustment_factor_extreme_cold() -> None:
    """Test korekčního faktoru pro extrémní zimu."""
    cold = WeatherData(
        datetime=datetime(2026, 1, 23, 12, 0),
        temperature=-10.0,
        cloud_cover=50,
        solar_radiation=100.0,
        wind_speed=5.0,
        precipitation=0.0,
    )

    factor = get_weather_adjustment_factor(cold)
    assert factor >= 1.0  # Extrémní zima = vyšší ceny


def test_get_weather_adjustment_factor_extreme_heat() -> None:
    """Test korekčního faktoru pro extrémní teplo."""
    hot = WeatherData(
        datetime=datetime(2026, 1, 23, 12, 0),
        temperature=35.0,
        cloud_cover=20,
        solar_radiation=600.0,
        wind_speed=3.0,
        precipitation=0.0,
    )

    factor = get_weather_adjustment_factor(hot)
    # Teplo + slunce: kombinace efektů
    assert 0.75 <= factor <= 1.25


def test_get_weather_adjustment_factor_bounds() -> None:
    """Test že korekční faktor je v rozumných mezích."""
    test_cases = [
        WeatherData(datetime(2026, 1, 23, 12), 0.0, 0, 1000.0, 20.0, 0.0),
        WeatherData(datetime(2026, 1, 23, 12), 40.0, 100, 0.0, 0.0, 10.0),
        WeatherData(datetime(2026, 1, 23, 12), -20.0, 50, 200.0, 5.0, 0.0),
    ]

    for data in test_cases:
        factor = get_weather_adjustment_factor(data)
        assert 0.75 <= factor <= 1.25, f"Factor {factor} out of bounds for {data}"
