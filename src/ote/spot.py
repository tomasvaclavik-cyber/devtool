"""OTE (Operátor trhu s elektřinou) API klient."""

from dataclasses import dataclass
from datetime import date, datetime

import httpx

OTE_BASE_URL = "https://www.ote-cr.cz"
# Anglická verze API vrací title u dataLine, což umožňuje rozlišit cenu od objemu
OTE_CHART_DATA_URL = f"{OTE_BASE_URL}/en/short-term-markets/electricity/day-ahead-market/@@chart-data"
CNB_RATE_URL = "https://www.cnb.cz/en/financial-markets/foreign-exchange-market/central-bank-exchange-rate-fixing/central-bank-exchange-rate-fixing/daily.txt"


@dataclass
class SpotPrice:
    """Spotová cena elektřiny."""

    time_from: datetime
    time_to: datetime
    price_eur: float
    price_czk: float


def fetch_eur_czk_rate() -> float:
    """Získá aktuální kurz EUR/CZK z ČNB.

    Returns:
        Kurz EUR/CZK.
    """
    with httpx.Client() as client:
        response = client.get(CNB_RATE_URL, timeout=30.0)
        response.raise_for_status()

    for line in response.text.splitlines():
        if "|EUR|" in line:
            # Formát: Country|Currency|Amount|Code|Rate
            parts = line.split("|")
            return float(parts[4])

    raise ValueError("EUR kurz nebyl nalezen v odpovědi ČNB")


def fetch_spot_prices(report_date: date | None = None) -> tuple[list[SpotPrice], float]:
    """Získá spotové ceny z OTE pro daný den.

    Args:
        report_date: Datum pro které získat ceny. Výchozí je dnes.

    Returns:
        Tuple (seznam spotových cen po 15 minutách, kurz EUR/CZK).
    """
    if report_date is None:
        report_date = date.today()

    # Získej kurz EUR/CZK
    eur_czk_rate = fetch_eur_czk_rate()

    params = {
        "report_date": report_date.strftime("%Y-%m-%d"),
    }

    with httpx.Client() as client:
        response = client.get(OTE_CHART_DATA_URL, params=params, timeout=30.0)
        response.raise_for_status()
        data = response.json()

    prices = []
    year = report_date.year

    # Data obsahují více dataLine - hledáme "15min price (EUR/MWh)"
    # x je 15minutový interval (1-96), y je cena
    if "data" in data and "dataLine" in data["data"]:
        price_data = None
        for dl in data["data"]["dataLine"]:
            if "price" in dl.get("title", "").lower() and "15min" in dl.get("title", "").lower():
                price_data = dl
                break

        if price_data:
            for point in price_data.get("point", []):
                interval = int(point["x"]) - 1  # OTE indexuje od 1
                price_eur = float(point["y"])
                price_czk = price_eur * eur_czk_rate
                # Převod intervalu na hodiny a minuty
                hour = interval // 4
                minute = (interval % 4) * 15
                time_from = datetime(year, report_date.month, report_date.day, hour, minute)
                minute_to = minute + 14
                time_to = datetime(year, report_date.month, report_date.day, hour, minute_to, 59)
                prices.append(SpotPrice(
                    time_from=time_from,
                    time_to=time_to,
                    price_eur=price_eur,
                    price_czk=price_czk,
                ))

    return prices, eur_czk_rate


def get_current_price(prices: list[SpotPrice]) -> SpotPrice | None:
    """Najde aktuální cenu podle času."""
    now = datetime.now()
    for price in prices:
        if price.time_from <= now <= price.time_to:
            return price
    return None
