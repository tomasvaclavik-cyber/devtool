"""OTE (Operátor trhu s elektřinou) API klient."""

from dataclasses import dataclass
from datetime import date, datetime

import httpx

OTE_BASE_URL = "https://www.ote-cr.cz"
OTE_CHART_DATA_URL = f"{OTE_BASE_URL}/cs/kratkodobe-trhy/elektrina/denni-trh/@@chart-data"


@dataclass
class SpotPrice:
    """Spotová cena elektřiny."""

    time_from: datetime
    time_to: datetime
    price_eur: float
    price_czk: float | None = None


def fetch_spot_prices(report_date: date | None = None) -> list[SpotPrice]:
    """Získá spotové ceny z OTE pro daný den.

    Args:
        report_date: Datum pro které získat ceny. Výchozí je dnes.

    Returns:
        Seznam spotových cen po 15 minutách.
    """
    if report_date is None:
        report_date = date.today()

    params = {
        "report_date": report_date.strftime("%Y-%m-%d"),
    }

    with httpx.Client() as client:
        response = client.get(OTE_CHART_DATA_URL, params=params, timeout=30.0)
        response.raise_for_status()
        data = response.json()

    prices = []
    year = report_date.year

    # Data obsahují dataLine - první položka jsou ceny v EUR/MWh
    # x je 15minutový interval (1-96), y je cena
    if "data" in data and "dataLine" in data["data"]:
        data_lines = data["data"]["dataLine"]
        if data_lines:
            for point in data_lines[0].get("point", []):
                interval = int(point["x"]) - 1  # OTE indexuje od 1
                price_eur = float(point["y"])
                # Převod intervalu na hodiny a minuty
                hour = interval // 4
                minute = (interval % 4) * 15
                time_from = datetime(year, report_date.month, report_date.day, hour, minute)
                minute_to = minute + 14
                time_to = datetime(year, report_date.month, report_date.day, hour, minute_to, 59)
                prices.append(SpotPrice(time_from=time_from, time_to=time_to, price_eur=price_eur))

    return prices


def get_current_price(prices: list[SpotPrice]) -> SpotPrice | None:
    """Najde aktuální cenu podle času."""
    now = datetime.now()
    for price in prices:
        if price.time_from <= now <= price.time_to:
            return price
    return None
