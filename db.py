"""SQLite-архив суточных показаний. Формат таблицы совместим со старым tst.py."""
import logging
import os
import sqlite3
from datetime import date, timedelta

log = logging.getLogger("merkury.db")

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(HERE, "your_database.db")  # путь от каталога скрипта, а не от cwd

SCHEMA = """
CREATE TABLE IF NOT EXISTS result_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sn TEXT NOT NULL,
    result_value REAL NOT NULL,
    date TEXT NOT NULL
)
"""

# Последнее показание каждого счётчика на дату <= upto. Ключ - sn, а не позиция строки.
LATEST_SQL = """
SELECT sn, result_value, date FROM result_data d
WHERE date = (SELECT MAX(date) FROM result_data WHERE sn = d.sn AND date <= ?)
"""


def open_db(path: str = DEFAULT_DB) -> sqlite3.Connection:
    con = sqlite3.connect(path, timeout=30)
    con.execute(SCHEMA)
    # Старая схема не гарантировала уникальность (sn, date): оставляем самую свежую строку.
    removed = con.execute(
        "DELETE FROM result_data WHERE id NOT IN "
        "(SELECT MAX(id) FROM result_data GROUP BY sn, date)"
    ).rowcount
    if removed:
        log.warning("удалено дублей (sn, date): %d", removed)
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_result_data_sn_date ON result_data(sn, date)")
    con.commit()
    return con


def save_reading(con: sqlite3.Connection, sn: str, value: float, day: str) -> None:
    """Одна строка на (sn, день); в течение дня перезаписывается последним показанием."""
    con.execute(
        "INSERT INTO result_data (sn, result_value, date) VALUES (?, ?, ?) "
        "ON CONFLICT(sn, date) DO UPDATE SET result_value = excluded.result_value",
        (sn, value, day),
    )
    con.commit()


def period_start(today: date, day: int = 28) -> date:
    """Начало расчётного периода: последнее `day`-е число, не позже today."""
    if today.day >= day:
        return today.replace(day=day)
    prev_month_last = today.replace(day=1) - timedelta(days=1)
    return prev_month_last.replace(day=day)


def latest_readings(con: sqlite3.Connection, upto: date) -> dict:
    """{sn: (значение, дата)} - последнее показание на дату <= upto."""
    return {sn: (v, d) for sn, v, d in con.execute(LATEST_SQL, (upto.isoformat(),))}


def base_reading(con: sqlite3.Connection, sn: str, start: date):
    """Показание счётчика на начало периода: последняя запись на дату <= start, либо None."""
    row = con.execute(
        "SELECT result_value FROM result_data WHERE sn = ? AND date <= ? ORDER BY date DESC LIMIT 1",
        (sn, start.isoformat()),
    ).fetchone()
    return row[0] if row else None
