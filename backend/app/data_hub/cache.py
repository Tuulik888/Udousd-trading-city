"""Local SQLite cache of OANDA candles, so backtests and the trade loop
don't refetch history from OANDA on every run.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Candle

DEFAULT_CACHE_PATH = Path(__file__).resolve().parent / "cache" / "candles.db"


class CandleCache:
    def __init__(self, db_path: str | Path = DEFAULT_CACHE_PATH) -> None:
        self.db_path = Path(db_path)
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS candles (
                instrument TEXT NOT NULL,
                granularity TEXT NOT NULL,
                time TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume INTEGER NOT NULL,
                PRIMARY KEY (instrument, granularity, time)
            )
            """
        )
        self._conn.commit()

    def upsert(self, instrument: str, granularity: str, candles: list[Candle]) -> int:
        rows = [
            (
                instrument,
                granularity,
                _iso(c.time),
                c.open,
                c.high,
                c.low,
                c.close,
                c.volume,
            )
            for c in candles
        ]
        self._conn.executemany(
            "INSERT OR REPLACE INTO candles "
            "(instrument, granularity, time, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        self._conn.commit()
        return len(rows)

    def query(
        self,
        instrument: str,
        granularity: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Candle]:
        sql = "SELECT time, open, high, low, close, volume FROM candles WHERE instrument = ? AND granularity = ?"
        params: list[str] = [instrument, granularity]
        if start is not None:
            sql += " AND time >= ?"
            params.append(_iso(start))
        if end is not None:
            sql += " AND time <= ?"
            params.append(_iso(end))
        sql += " ORDER BY time ASC"
        cur = self._conn.execute(sql, params)
        return [
            Candle(
                time=datetime.fromisoformat(row[0]),
                open=row[1],
                high=row[2],
                low=row[3],
                close=row[4],
                volume=row[5],
            )
            for row in cur.fetchall()
        ]

    def latest_time(self, instrument: str, granularity: str) -> datetime | None:
        cur = self._conn.execute(
            "SELECT MAX(time) FROM candles WHERE instrument = ? AND granularity = ?",
            (instrument, granularity),
        )
        row = cur.fetchone()
        if row is None or row[0] is None:
            return None
        return datetime.fromisoformat(row[0])

    def close(self) -> None:
        self._conn.close()


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()
