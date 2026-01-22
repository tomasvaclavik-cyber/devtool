"""Databázový modul pro ukládání spotových cen."""

import sqlite3
from datetime import date, datetime
from pathlib import Path

from ote.spot import SpotPrice

# Výchozí cesta k databázi v home adresáři
DEFAULT_DB_PATH = Path.home() / ".ote" / "prices.db"


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Vytvoří připojení k databázi."""
    if db_path is None:
        db_path = DEFAULT_DB_PATH

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


def get_daily_stats(conn: sqlite3.Connection, report_date: date) -> dict | None:
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
