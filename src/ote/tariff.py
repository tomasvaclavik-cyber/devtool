"""Výpočet koncové ceny elektřiny podle mého tarifu (převzato z Home Assistantu).

Obchodník Electree (spot), distribuce ČEZ D25d, ceny 2026 bez OZE.
Ceny poplatků jsou v Kč/kWh, spot se přepočítává z CZK/MWh.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# DPH se v HA šabloně přičítá jen ke spotové ceně
VAT = 1.21

ELECTREE_FEE = 0.3509  # poplatek za odběr ze spotu
DISTRIBUTION_VT = 2.72546  # D25d, ČEZ – vysoký tarif
DISTRIBUTION_NT = 0.14097  # D25d, ČEZ – nízký tarif
SYSTEM_SERVICES = 0.19873
ENERGY_TAX = 0.03424

# Výkup (prodej do sítě): spot bez DPH minus služby obchodu Electree
# 499 Kč/MWh s DPH (412,39 Kč bez DPH) = 0,499 Kč/kWh
SELL_FEE = 0.499

# Násobek pro dlaždici „Bojler" (input_number × 2,4 Kč)
BOILER_MULTIPLIER = 2.4

# Hodiny nízkého tarifu (HDO) – [od, do)
LOW_TARIFF_HOURS = ((0, 6), (19, 21))


@dataclass
class TariffPrice:
    """Koncová cena pro jeden interval."""

    time_from: datetime
    spot_kwh: float
    is_low_tariff: bool
    total_kwh: float


def is_low_tariff(hour: int) -> bool:
    """Vrátí True, pokud hodina spadá do nízkého tarifu."""
    return any(start <= hour < end for start, end in LOW_TARIFF_HOURS)


def total_price_kwh(spot_kwh: float, low_tariff: bool) -> float:
    """Koncová cena v Kč/kWh pro spotovou cenu v Kč/kWh (bez DPH)."""
    distribution = DISTRIBUTION_NT if low_tariff else DISTRIBUTION_VT
    return spot_kwh * VAT + ELECTREE_FEE + distribution + SYSTEM_SERVICES + ENERGY_TAX


def sell_price_kwh(spot_kwh: float) -> float:
    """Výkupní cena v Kč/kWh: spot bez DPH minus poplatek Electree za služby obchodu."""
    return spot_kwh - SELL_FEE


def low_tariff_price(spot_kwh: float) -> float:
    """Cena v nízkém tarifu (senzor „Nízký tarif cena")."""
    return round(total_price_kwh(spot_kwh, low_tariff=True), 4)


def high_tariff_price(spot_kwh: float) -> float:
    """Cena ve vysokém tarifu (senzor „Vysoký tarif cena")."""
    return round(total_price_kwh(spot_kwh, low_tariff=False), 4)


def boiler_price(value: float) -> float:
    """Dlaždice „Bojler" – zadaná hodnota × 2,4 Kč."""
    return round(value * BOILER_MULTIPLIER, 2)


def czk_mwh_to_kwh(price_czk_mwh: float) -> float:
    """Převod CZK/MWh → Kč/kWh."""
    return price_czk_mwh / 1000


def compute_tariff_prices(
    prices: list[tuple[datetime, float]],
) -> list[TariffPrice]:
    """Spočítá koncové ceny pro seznam (čas, spot v CZK/MWh)."""
    result = []
    for time_from, price_czk_mwh in prices:
        spot_kwh = czk_mwh_to_kwh(price_czk_mwh)
        low = is_low_tariff(time_from.hour)
        result.append(TariffPrice(
            time_from=time_from,
            spot_kwh=spot_kwh,
            is_low_tariff=low,
            total_kwh=total_price_kwh(spot_kwh, low),
        ))
    return result


# Odchylka od průměru srovnávacích cen, od které je cena „vysoká" / „nízká"
LEVEL_TOLERANCE = 0.15


def price_level(current: float, references: list[float]) -> str | None:
    """Zhodnotí cenu vůči průměru srovnávacích cen: „nízká" / „normální" / „vysoká"."""
    if not references:
        return None
    avg = sum(references) / len(references)
    if current > avg * (1 + LEVEL_TOLERANCE):
        return "vysoká"
    if current < avg * (1 - LEVEL_TOLERANCE):
        return "nízká"
    return "normální"
