"""Testy pro výpočet koncové ceny podle tarifu."""

from datetime import datetime

import pytest

from ote.tariff import (
    compute_tariff_prices,
    czk_mwh_to_kwh,
    high_tariff_price,
    is_low_tariff,
    low_tariff_price,
    price_level,
    sell_price_kwh,
    total_price_kwh,
)


@pytest.mark.parametrize(
    ("hour", "expected"),
    [(0, True), (5, True), (6, False), (12, False), (18, False), (19, True), (20, True),
     (21, False), (23, False)],
)
def test_is_low_tariff(hour: int, expected: bool) -> None:
    assert is_low_tariff(hour) is expected


def test_total_price_matches_ha_template() -> None:
    # Spot 2,00 Kč/kWh: 2 × 1,21 + 0,3509 + dist + 0,19873 + 0,03424
    assert low_tariff_price(2.0) == pytest.approx(
        2.42 + 0.3509 + 0.14097 + 0.19873 + 0.03424, abs=1e-4
    )
    assert high_tariff_price(2.0) == pytest.approx(
        2.42 + 0.3509 + 2.72546 + 0.19873 + 0.03424, abs=1e-4
    )


def test_negative_spot() -> None:
    assert total_price_kwh(-0.5, low_tariff=True) == pytest.approx(
        -0.605 + 0.3509 + 0.14097 + 0.19873 + 0.03424
    )


def test_compute_tariff_prices() -> None:
    rows = compute_tariff_prices([
        (datetime(2026, 10, 20, 3, 0), 1500.0),
        (datetime(2026, 10, 20, 12, 15), 1500.0),
    ])
    assert czk_mwh_to_kwh(1500.0) == 1.5
    assert rows[0].is_low_tariff and not rows[1].is_low_tariff
    assert rows[0].spot_kwh == 1.5
    assert rows[1].total_kwh - rows[0].total_kwh == pytest.approx(2.72546 - 0.14097)


@pytest.mark.parametrize(
    ("current", "references", "expected"),
    [
        (7.0, [7.0, 7.2], "normální"),
        (8.5, [7.0, 7.2], "vysoká"),
        (5.5, [7.0, 7.2], "nízká"),
        (7.0, [7.0], "normální"),
        (7.0, [], None),
    ],
)
def test_price_level(current: float, references: list[float], expected: str | None) -> None:
    assert price_level(current, references) == expected


def test_sell_price() -> None:
    # Spot 2,00 Kč/kWh bez DPH − 499 Kč/MWh s DPH za služby obchodu
    assert sell_price_kwh(2.0) == pytest.approx(1.501)
    # Při záporném spotu se za dodávku do sítě platí
    assert sell_price_kwh(-0.1) == pytest.approx(-0.599)
