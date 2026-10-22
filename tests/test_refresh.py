"""Testy pro výpočet času obnovy dashboardu."""

from datetime import datetime

import pytest

from ote.spot import next_refresh_time


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 10, 22, 8, 0, 0), datetime(2026, 10, 22, 8, 1)),
        (datetime(2026, 10, 22, 8, 0, 59), datetime(2026, 10, 22, 8, 1)),
        (datetime(2026, 10, 22, 8, 1, 0), datetime(2026, 10, 22, 8, 16)),
        (datetime(2026, 10, 22, 8, 7, 30), datetime(2026, 10, 22, 8, 16)),
        (datetime(2026, 10, 22, 8, 16, 0, 1), datetime(2026, 10, 22, 8, 31)),
        (datetime(2026, 10, 22, 8, 44, 0), datetime(2026, 10, 22, 8, 46)),
        (datetime(2026, 10, 22, 23, 50, 0), datetime(2026, 10, 23, 0, 1)),
    ],
)
def test_next_refresh_time(now: datetime, expected: datetime) -> None:
    assert next_refresh_time(now) == expected
