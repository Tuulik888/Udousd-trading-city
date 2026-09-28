"""DataHub: ties the OANDA client and the local candle cache together.

Callers (backtest_lab, main_tower) should go through this, not the raw
OandaClient, so they always get cached history plus only the freshest
missing candles fetched over the wire.
"""
from __future__ import annotations

from .cache import CandleCache
from .models import Candle
from .oanda_client import OandaClient


class DataHub:
    def __init__(self, client: OandaClient, cache: CandleCache) -> None:
        self.client = client
        self.cache = cache

    def get_candles(self, instrument: str, granularity: str, count: int = 500) -> list[Candle]:
        """Return the most recent `count` candles, fetching+caching any
        that aren't already cached."""
        fresh = self.client.get_candles(instrument, granularity, count=count)
        self.cache.upsert(instrument, granularity, fresh)
        return self.cache.query(instrument, granularity)[-count:]

    def backfill(
        self,
        instrument: str,
        granularity: str,
        from_time,
        to_time,
        chunk_days: int = 10,
    ) -> int:
        """Fetch historical candles in chunks between from_time and
        to_time (OANDA caps a single request's candle count), caching
        each chunk. Returns total candles cached."""
        from datetime import timedelta

        total = 0
        cursor = from_time
        step = timedelta(days=chunk_days)
        while cursor < to_time:
            chunk_end = min(cursor + step, to_time)
            candles = self.client.get_candles(
                instrument, granularity, from_time=cursor, to_time=chunk_end
            )
            total += self.cache.upsert(instrument, granularity, candles)
            cursor = chunk_end
        return total
