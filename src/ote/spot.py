"""OTE (Operátor trhu s elektřinou) API klient."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

# Časové pásmo pro Českou republiku (OTE data jsou v tomto pásmu)
PRAGUE_TZ = ZoneInfo("Europe/Prague")
INTERVAL = timedelta(minutes=15)

OTE_BASE_URL = "https://www.ote-cr.cz"
OTE_CHART_DATA_URL = f"{OTE_BASE_URL}/pw-data/chart-data/01"
CNB_RATE_URL = (
    "https://www.cnb.cz/en/financial-markets/foreign-exchange-market/"
    "central-bank-exchange-rate-fixing/central-bank-exchange-rate-fixing/daily.txt"
)


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
        "language": "en",
    }

    with httpx.Client(follow_redirects=True) as client:
        response = client.get(OTE_CHART_DATA_URL, params=params, timeout=30.0)
        response.raise_for_status()
        data = response.json()

    prices = []

    # Data obsahují více dataLine - hledáme "15min price (EUR/MWh)"
    # x je 15minutový interval (1-96, při změně času 92 nebo 100), y je cena
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
                time_from, time_to = interval_times(report_date, interval)
                prices.append(SpotPrice(
                    time_from=time_from,
                    time_to=time_to,
                    price_eur=price_eur,
                    price_czk=price_czk,
                ))

    return prices, eur_czk_rate


def interval_times(report_date: date, interval: int) -> tuple[datetime, datetime]:
    """Vrátí (time_from, time_to) n-tého 15min intervalu dne v pražském čase (naive).

    Počítá se přes UTC, aby seděly dny se změnou času: jarní den má 92 intervalů
    (po 01:45 následuje 03:00), podzimní 100 (02:00–02:45 je dvakrát, druhý výskyt
    má ``fold=1``).
    """
    day_start = datetime.combine(report_date, time(), PRAGUE_TZ).astimezone(timezone.utc)
    start = day_start + interval * INTERVAL
    time_from = start.astimezone(PRAGUE_TZ).replace(tzinfo=None)
    time_to = (start + INTERVAL - timedelta(seconds=1)).astimezone(PRAGUE_TZ).replace(tzinfo=None)
    return time_from, time_to


def slot_label(dt: datetime) -> str:
    """Popisek intervalu HH:MM; opakovaná hodina při přechodu na zimní čas se odliší."""
    return f"{dt:%H:%M} (zimní)" if dt.fold else f"{dt:%H:%M}"


def _is_current(price: SpotPrice, now: datetime) -> bool:
    # Porovnání v UTC – naive časy z OTE jsou pražské, fold rozliší opakovanou hodinu
    start = price.time_from.replace(tzinfo=PRAGUE_TZ).astimezone(timezone.utc)
    return start <= now.astimezone(timezone.utc) < start + INTERVAL


def get_current_price(prices: list[SpotPrice]) -> SpotPrice | None:
    """Najde aktuální cenu podle času.

    Používá české časové pásmo (Europe/Prague), protože OTE data
    jsou v tomto pásmu.
    """
    now = datetime.now(PRAGUE_TZ)
    for price in prices:
        if _is_current(price, now):
            return price
    return None


def get_current_price_debug(prices: list[SpotPrice]) -> tuple[SpotPrice | None, str]:
    """Najde aktuální cenu s debug informacemi.

    Returns:
        Tuple (aktuální cena nebo None, debug string s použitým časem)
    """
    now = datetime.now(PRAGUE_TZ)
    debug_info = f"now={now.isoformat()}, utc={now.astimezone(timezone.utc).isoformat()}"
    for price in prices:
        if _is_current(price, now):
            return price, debug_info
    return None, debug_info


def next_refresh_time(now: datetime, offset_seconds: int = 5) -> datetime:
    """Vrátí nejbližší čas obnovy: začátek 15min intervalu + offset (xx:00:05, :15:05, …).

    Day-ahead ceny jsou známé předem, stačí obnovit hned po začátku intervalu.
    Pár sekund rezervy chrání před časovačem, který odbije o zlomek sekundy dřív.
    """
    slot_start = now.replace(minute=now.minute // 15 * 15, second=0, microsecond=0)
    candidate = slot_start + timedelta(seconds=offset_seconds)
    if candidate <= now:
        candidate += timedelta(minutes=15)
    return candidate
