"""Testy pro výpočet času obnovy dashboardu."""

from datetime import datetime

import pytest

from ote.spot import next_refresh_time


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 10, 22, 8, 0, 0), datetime(2026, 10, 22, 8, 0, 5)),
        (datetime(2026, 10, 22, 8, 0, 4, 999999), datetime(2026, 10, 22, 8, 0, 5)),
        (datetime(2026, 10, 22, 8, 0, 5), datetime(2026, 10, 22, 8, 15, 5)),
        (datetime(2026, 10, 22, 8, 7, 30), datetime(2026, 10, 22, 8, 15, 5)),
        # Časovač odbil o zlomek sekundy dřív – obnova hned po začátku intervalu
        (datetime(2026, 10, 22, 8, 14, 59, 900000), datetime(2026, 10, 22, 8, 15, 5)),
        (datetime(2026, 10, 22, 8, 44, 0), datetime(2026, 10, 22, 8, 45, 5)),
        (datetime(2026, 10, 22, 23, 50, 0), datetime(2026, 10, 23, 0, 0, 5)),
    ],
)
def test_next_refresh_time(now: datetime, expected: datetime) -> None:
    assert next_refresh_time(now) == expected
