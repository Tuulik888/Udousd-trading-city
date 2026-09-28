from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
import respx

from app.data_hub.cache import CandleCache
from app.data_hub.models import Candle
from app.data_hub.oanda_client import OandaClient, OandaConfigError
from app.data_hub.service import DataHub

PRACTICE_URL = "https://api-fxpractice.oanda.com"

RAW_CANDLES_PAYLOAD = {
    "candles": [
        {
            "complete": True,
            "volume": 120,
            "time": "2026-01-05T00:00:00.000000000Z",
            "mid": {"o": "1.10000", "h": "1.10100", "l": "1.09900", "c": "1.10050"},
        },
        {
            "complete": True,
            "volume": 98,
            "time": "2026-01-05T00:15:00.000000000Z",
            "mid": {"o": "1.10050", "h": "1.10200", "l": "1.10000", "c": "1.10150"},
        },
        {
            # incomplete candles (still forming) must be dropped
            "complete": False,
            "volume": 4,
            "time": "2026-01-05T00:30:00.000000000Z",
            "mid": {"o": "1.10150", "h": "1.10150", "l": "1.10150", "c": "1.10150"},
        },
    ]
}


class TestOandaClientPracticeOnly:
    def test_practice_url_constructs_fine(self):
        client = OandaClient(api_key="k", account_id="a", base_url=PRACTICE_URL)
        assert client.base_url == PRACTICE_URL

    @pytest.mark.parametrize(
        "url",
        [
            "https://api-fxtrade.oanda.com",
            "http://api-fxpractice.oanda.com",  # not https
            "https://evil.com",
        ],
    )
    def test_live_or_bad_url_rejected(self, url):
        with pytest.raises(OandaConfigError):
            OandaClient(api_key="k", account_id="a", base_url=url)


class TestOandaClientCandles:
    @respx.mock
    def test_get_candles_parses_and_drops_incomplete(self):
        respx.get(f"{PRACTICE_URL}/v3/instruments/EUR_USD/candles").mock(
            return_value=httpx.Response(200, json=RAW_CANDLES_PAYLOAD)
        )
        client = OandaClient(api_key="k", account_id="a", base_url=PRACTICE_URL)
        candles = client.get_candles("EUR_USD", "M15", count=500)

        assert len(candles) == 2
        assert candles[0].open == pytest.approx(1.10000)
        assert candles[0].close == pytest.approx(1.10050)
        assert candles[0].time == datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)

    @respx.mock
    def test_get_candles_raises_on_http_error(self):
        respx.get(f"{PRACTICE_URL}/v3/instruments/EUR_USD/candles").mock(
            return_value=httpx.Response(401, json={"errorMessage": "bad token"})
        )
        client = OandaClient(api_key="bad", account_id="a", base_url=PRACTICE_URL)
        with pytest.raises(httpx.HTTPStatusError):
            client.get_candles("EUR_USD", "M15")


class TestCandleCache:
    def make_candles(self) -> list[Candle]:
        return [
            Candle(
                time=datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc),
                open=1.1,
                high=1.101,
                low=1.099,
                close=1.1005,
                volume=100,
            ),
            Candle(
                time=datetime(2026, 1, 5, 0, 15, tzinfo=timezone.utc),
                open=1.1005,
                high=1.102,
                low=1.1,
                close=1.1015,
                volume=90,
            ),
        ]

    def test_upsert_then_query_roundtrip(self):
        cache = CandleCache(db_path=":memory:")
        inserted = cache.upsert("EUR_USD", "M15", self.make_candles())
        assert inserted == 2

        result = cache.query("EUR_USD", "M15")
        assert len(result) == 2
        assert result[0].close == pytest.approx(1.1005)

    def test_upsert_is_idempotent_on_same_time(self):
        cache = CandleCache(db_path=":memory:")
        candles = self.make_candles()
        cache.upsert("EUR_USD", "M15", candles)
        # re-insert with an updated close for the same timestamps
        updated = [
            Candle(time=c.time, open=c.open, high=c.high, low=c.low, close=9.9, volume=c.volume)
            for c in candles
        ]
        cache.upsert("EUR_USD", "M15", updated)

        result = cache.query("EUR_USD", "M15")
        assert len(result) == 2  # no duplicates
        assert all(c.close == pytest.approx(9.9) for c in result)

    def test_latest_time_returns_none_when_empty(self):
        cache = CandleCache(db_path=":memory:")
        assert cache.latest_time("EUR_USD", "M15") is None

    def test_latest_time_returns_max(self):
        cache = CandleCache(db_path=":memory:")
        cache.upsert("EUR_USD", "M15", self.make_candles())
        assert cache.latest_time("EUR_USD", "M15") == datetime(2026, 1, 5, 0, 15, tzinfo=timezone.utc)

    def test_query_respects_instrument_and_granularity(self):
        cache = CandleCache(db_path=":memory:")
        cache.upsert("EUR_USD", "M15", self.make_candles())
        cache.upsert("EUR_USD", "H1", self.make_candles())
        cache.upsert("GBP_USD", "M15", self.make_candles())

        assert len(cache.query("EUR_USD", "M15")) == 2
        assert len(cache.query("EUR_USD", "H1")) == 2
        assert len(cache.query("GBP_USD", "M15")) == 2


class TestDataHub:
    @respx.mock
    def test_get_candles_fetches_and_caches(self):
        respx.get(f"{PRACTICE_URL}/v3/instruments/EUR_USD/candles").mock(
            return_value=httpx.Response(200, json=RAW_CANDLES_PAYLOAD)
        )
        client = OandaClient(api_key="k", account_id="a", base_url=PRACTICE_URL)
        cache = CandleCache(db_path=":memory:")
        hub = DataHub(client=client, cache=cache)

        result = hub.get_candles("EUR_USD", "M15", count=500)
        assert len(result) == 2
        # cache now has them without another HTTP call
        assert len(cache.query("EUR_USD", "M15")) == 2
