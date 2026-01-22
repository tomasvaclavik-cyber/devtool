"""Databázový modul pro ukládání spotových cen."""

import os
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from ote.spot import SpotPrice


def get_default_db_path() -> Path:
    """Vrátí výchozí cestu k databázi.

    Používá OTE_DB_PATH env proměnnou, nebo ~/.ote/prices.db
    """
    env_path = os.environ.get("OTE_DB_PATH")
    if env_path:
        return Path(env_path)
    return Path.home() / ".ote" / "prices.db"


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Vytvoří připojení k databázi."""
    if db_path is None:
        db_path = get_default_db_path()

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Inicializuje databázové schéma."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS spot_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_date DATE NOT NULL,
            time_from DATETIME NOT NULL,
            time_to DATETIME NOT NULL,
            price_eur REAL NOT NULL,
            price_czk REAL NOT NULL,
            eur_czk_rate REAL NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(report_date, time_from)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_report_date ON spot_prices(report_date)
    """)
    conn.commit()


def save_prices(
    conn: sqlite3.Connection,
    report_date: date,
    prices: list[SpotPrice],
    eur_czk_rate: float,
) -> int:
    """Uloží ceny do databáze.

    Returns:
        Počet uložených záznamů.
    """
    init_db(conn)

    # Použij INSERT OR REPLACE pro aktualizaci existujících záznamů
    cursor = conn.executemany(
        """
        INSERT OR REPLACE INTO spot_prices
        (report_date, time_from, time_to, price_eur, price_czk, eur_czk_rate)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                report_date.isoformat(),
                p.time_from.isoformat(),
                p.time_to.isoformat(),
                p.price_eur,
                p.price_czk,
                eur_czk_rate,
            )
            for p in prices
        ],
    )
    conn.commit()
    return cursor.rowcount


def get_prices_for_date(
    conn: sqlite3.Connection,
    report_date: date,
) -> list[SpotPrice]:
    """Načte ceny z databáze pro daný den."""
    init_db(conn)

    cursor = conn.execute(
        """
        SELECT time_from, time_to, price_eur, price_czk
        FROM spot_prices
        WHERE report_date = ?
        ORDER BY time_from
        """,
        (report_date.isoformat(),),
    )

    return [
        SpotPrice(
            time_from=datetime.fromisoformat(row["time_from"]),
            time_to=datetime.fromisoformat(row["time_to"]),
            price_eur=row["price_eur"],
            price_czk=row["price_czk"],
        )
        for row in cursor.fetchall()
    ]


def get_available_dates(conn: sqlite3.Connection) -> list[date]:
    """Vrátí seznam dostupných dat v databázi."""
    init_db(conn)

    cursor = conn.execute("""
        SELECT DISTINCT report_date FROM spot_prices ORDER BY report_date DESC
    """)

    return [date.fromisoformat(row["report_date"]) for row in cursor.fetchall()]


def get_daily_stats(conn: sqlite3.Connection, report_date: date) -> dict[str, float] | None:
    """Vrátí statistiky pro daný den."""
    init_db(conn)

    cursor = conn.execute(
        """
        SELECT
            MIN(price_czk) as min_price,
            MAX(price_czk) as max_price,
            AVG(price_czk) as avg_price,
            COUNT(*) as count,
            MAX(eur_czk_rate) as eur_czk_rate
        FROM spot_prices
        WHERE report_date = ?
        """,
        (report_date.isoformat(),),
    )

    row = cursor.fetchone()
    if row and row["count"] > 0:
        return {
            "min": row["min_price"],
            "max": row["max_price"],
            "avg": row["avg_price"],
            "count": row["count"],
            "eur_czk_rate": row["eur_czk_rate"],
        }
    return None


def get_prices_for_range(
    conn: sqlite3.Connection,
    start_date: date,
    end_date: date,
) -> list[SpotPrice]:
    """Načte ceny z databáze pro rozsah dat."""
    init_db(conn)

    cursor = conn.execute(
        """
        SELECT time_from, time_to, price_eur, price_czk
        FROM spot_prices
        WHERE report_date >= ? AND report_date <= ?
        ORDER BY time_from
        """,
        (start_date.isoformat(), end_date.isoformat()),
    )

    return [
        SpotPrice(
            time_from=datetime.fromisoformat(row["time_from"]),
            time_to=datetime.fromisoformat(row["time_to"]),
            price_eur=row["price_eur"],
            price_czk=row["price_czk"],
        )
        for row in cursor.fetchall()
    ]


def get_hourly_aggregates(
    conn: sqlite3.Connection,
    days_back: int = 30,
) -> list[dict[str, float]]:
    """Vrátí průměrné ceny agregované podle hodiny.

    Returns:
        Seznam slovníků s klíči: hour, avg_price, min_price, max_price, count
    """
    init_db(conn)

    cursor = conn.execute(
        """
        SELECT
            CAST(strftime('%H', time_from) AS INTEGER) as hour,
            AVG(price_czk) as avg_price,
            MIN(price_czk) as min_price,
            MAX(price_czk) as max_price,
            COUNT(*) as count
        FROM spot_prices
        WHERE report_date >= date('now', ?)
        GROUP BY hour
        ORDER BY hour
        """,
        (f"-{days_back} days",),
    )

    return [
        {
            "hour": row["hour"],
            "avg_price": row["avg_price"],
            "min_price": row["min_price"],
            "max_price": row["max_price"],
            "count": row["count"],
        }
        for row in cursor.fetchall()
    ]


def get_weekday_aggregates(
    conn: sqlite3.Connection,
    days_back: int = 60,
) -> list[dict[str, float]]:
    """Vrátí průměrné ceny agregované podle dne v týdnu a hodiny.

    Returns:
        Seznam slovníků s klíči: weekday (0=Monday), hour, avg_price, count
    """
    init_db(conn)

    cursor = conn.execute(
        """
        SELECT
            CAST(strftime('%w', time_from) AS INTEGER) as weekday_sun,
            CAST(strftime('%H', time_from) AS INTEGER) as hour,
            AVG(price_czk) as avg_price,
            COUNT(*) as count
        FROM spot_prices
        WHERE report_date >= date('now', ?)
        GROUP BY weekday_sun, hour
        ORDER BY weekday_sun, hour
        """,
        (f"-{days_back} days",),
    )

    # Převod z neděle=0 na pondělí=0
    return [
        {
            "weekday": (row["weekday_sun"] - 1) % 7,  # 0=Monday, 6=Sunday
            "hour": row["hour"],
            "avg_price": row["avg_price"],
            "count": row["count"],
        }
        for row in cursor.fetchall()
    ]


def get_data_days_count(conn: sqlite3.Connection) -> int:
    """Vrátí počet dnů s daty v databázi."""
    init_db(conn)

    cursor = conn.execute("""
        SELECT COUNT(DISTINCT report_date) as count FROM spot_prices
    """)

    row = cursor.fetchone()
    return row["count"] if row else 0


def get_overall_stats(conn: sqlite3.Connection, days_back: int = 30) -> dict[str, float] | None:
    """Vrátí celkové statistiky za období."""
    init_db(conn)

    cursor = conn.execute(
        """
        SELECT
            AVG(price_czk) as avg_price,
            MIN(price_czk) as min_price,
            MAX(price_czk) as max_price,
            COUNT(*) as count
        FROM spot_prices
        WHERE report_date >= date('now', ?)
        """,
        (f"-{days_back} days",),
    )

    row = cursor.fetchone()
    if row and row["count"] > 0:
        return {
            "avg": row["avg_price"],
            "min": row["min_price"],
            "max": row["max_price"],
            "count": row["count"],
        }
    return None


@dataclass
class NegativePriceHour:
    """Hodina s negativní cenou."""

    date: date
    hour: int
    price_czk: float


@dataclass
class DailyAverage:
    """Denní průměry cen."""

    date: date
    avg_price: float
    min_price: float
    max_price: float


def get_negative_price_hours(
    conn: sqlite3.Connection,
    days_back: int = 30,
) -> list[NegativePriceHour]:
    """Vrátí hodiny s negativní nebo nulovou cenou.

    Returns:
        Seznam NegativePriceHour.
    """
    init_db(conn)

    cursor = conn.execute(
        """
        SELECT
            report_date,
            CAST(strftime('%H', time_from) AS INTEGER) as hour,
            MIN(price_czk) as price_czk
        FROM spot_prices
        WHERE report_date >= date('now', ?)
          AND price_czk <= 0
        GROUP BY report_date, hour
        ORDER BY report_date DESC, hour
        """,
        (f"-{days_back} days",),
    )

    return [
        NegativePriceHour(
            date=date.fromisoformat(row["report_date"]),
            hour=row["hour"],
            price_czk=row["price_czk"],
        )
        for row in cursor.fetchall()
    ]


def get_daily_averages(
    conn: sqlite3.Connection,
    days_back: int = 60,
) -> list[DailyAverage]:
    """Vrátí denní průměry cen.

    Returns:
        Seznam DailyAverage.
    """
    init_db(conn)

    cursor = conn.execute(
        """
        SELECT
            report_date,
            AVG(price_czk) as avg_price,
            MIN(price_czk) as min_price,
            MAX(price_czk) as max_price
        FROM spot_prices
        WHERE report_date >= date('now', ?)
        GROUP BY report_date
        ORDER BY report_date
        """,
        (f"-{days_back} days",),
    )

    return [
        DailyAverage(
            date=date.fromisoformat(row["report_date"]),
            avg_price=row["avg_price"],
            min_price=row["min_price"],
            max_price=row["max_price"],
        )
        for row in cursor.fetchall()
    ]
