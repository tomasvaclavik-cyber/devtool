"""Testy pro převod intervalů OTE na časy, včetně dnů se změnou času."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from ote.spot import SpotPrice, _is_current, interval_times, slot_label

PRAGUE_TZ = ZoneInfo("Europe/Prague")


def _day(report_date: date, count: int) -> list[datetime]:
    return [interval_times(report_date, i)[0] for i in range(count)]


def test_bezny_den() -> None:
    times = _day(date(2026, 10, 24), 96)
    assert times[0] == datetime(2026, 10, 24, 0, 0)
    assert times[-1] == datetime(2026, 10, 24, 23, 45)
    assert interval_times(date(2026, 10, 24), 0)[1] == datetime(2026, 10, 24, 0, 14, 59)


def test_podzimni_zmena_casu_100_intervalu() -> None:
    times = _day(date(2026, 10, 25), 100)
    assert times[-1] == datetime(2026, 10, 25, 23, 45)
    # 02:00–02:45 dvakrát, druhý výskyt (zimní čas) má fold=1
    assert [(t.hour, t.minute, t.fold) for t in times[8:16]] == [
        (2, 0, 0), (2, 15, 0), (2, 30, 0), (2, 45, 0),
        (2, 0, 1), (2, 15, 1), (2, 30, 1), (2, 45, 1),
    ]
    assert interval_times(date(2026, 10, 25), 15)[1].fold == 1
    labels = [slot_label(t) for t in times]
    assert len(set(labels)) == 100
    assert labels[12] == "02:00 (zimní)"


def test_jarni_zmena_casu_92_intervalu() -> None:
    times = _day(date(2026, 3, 29), 92)
    assert times[7] == datetime(2026, 3, 29, 1, 45)
    assert times[8] == datetime(2026, 3, 29, 3, 0)
    assert times[-1] == datetime(2026, 3, 29, 23, 45)


def test_aktualni_cena_v_opakovane_hodine() -> None:
    prices = [
        SpotPrice(*interval_times(date(2026, 10, 25), i), price_eur=i, price_czk=i)
        for i in range(100)
    ]
    # 02:05 letního času (CEST) = interval 8, 02:05 zimního (CET) = interval 12
    cest = datetime(2026, 10, 25, 2, 5, tzinfo=PRAGUE_TZ)
    cet = datetime(2026, 10, 25, 2, 5, fold=1, tzinfo=PRAGUE_TZ)
    assert [p.price_eur for p in prices if _is_current(p, cest)] == [8]
    assert [p.price_eur for p in prices if _is_current(p, cet)] == [12]
