"""Thin, practice-only HTTP client for the OANDA v3 REST API.

Defense in depth: even if `Settings.oanda_base_url` is misconfigured or
an env var is tampered with, this client refuses at construction time to
talk to anything but the OANDA practice host. This check is independent
of (and in addition to) the Risk Vault's own `assert_practice_url` — see
AGENTS.md section 2.
"""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from app.config import OANDA_PRACTICE_URL

from .models import Candle

_ALLOWED_HOST = "api-fxpractice.oanda.com"


class OandaConfigError(Exception):
    """Raised when the client is configured against a non-practice host."""


def assert_practice_host(base_url: str) -> None:
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or parsed.netloc != _ALLOWED_HOST:
        raise OandaConfigError(
            f"Refusing to talk to non-practice OANDA host: {base_url!r}. "
            f"Only https://{_ALLOWED_HOST} is permitted."
        )


class OandaClient:
    """Wraps the handful of OANDA v3 endpoints this project needs."""

    def __init__(
        self,
        api_key: str,
        account_id: str,
        base_url: str = OANDA_PRACTICE_URL,
        http_client: httpx.Client | None = None,
    ) -> None:
        assert_practice_host(base_url)
        self.account_id = account_id
        self.base_url = base_url.rstrip("/")
        self._client = http_client or httpx.Client(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=15.0,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "OandaClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    def get_candles(
        self,
        instrument: str,
        granularity: str,
        count: int = 500,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
    ) -> list[Candle]:
        params: dict[str, str | int] = {"granularity": granularity, "price": "M"}
        if from_time is not None:
            params["from"] = _to_rfc3339(from_time)
            if to_time is not None:
                params["to"] = _to_rfc3339(to_time)
        else:
            params["count"] = count

        resp = self._client.get(f"/v3/instruments/{instrument}/candles", params=params)
        resp.raise_for_status()
        payload = resp.json()
        return [
            _parse_candle(raw) for raw in payload.get("candles", []) if raw.get("complete")
        ]

    # ------------------------------------------------------------------
    # Account / trading (used by paper_park)
    # ------------------------------------------------------------------

    def get_account_summary(self) -> dict:
        resp = self._client.get(f"/v3/accounts/{self.account_id}/summary")
        resp.raise_for_status()
        return resp.json()["account"]

    def place_market_order(
        self,
        instrument: str,
        units: float,
        stop_loss_price: float,
        take_profit_price: float,
    ) -> dict:
        """units: positive for long, negative for short."""
        body = {
            "order": {
                "type": "MARKET",
                "instrument": instrument,
                "units": str(round(units)),
                "timeInForce": "FOK",
                "positionFill": "DEFAULT",
                "stopLossOnFill": {"price": f"{stop_loss_price:.5f}"},
                "takeProfitOnFill": {"price": f"{take_profit_price:.5f}"},
            }
        }
        resp = self._client.post(f"/v3/accounts/{self.account_id}/orders", json=body)
        resp.raise_for_status()
        return resp.json()

    def close_trade(self, trade_id: str) -> dict:
        resp = self._client.put(
            f"/v3/accounts/{self.account_id}/trades/{trade_id}/close"
        )
        resp.raise_for_status()
        return resp.json()

    def list_open_trades(self) -> list[dict]:
        resp = self._client.get(f"/v3/accounts/{self.account_id}/openTrades")
        resp.raise_for_status()
        return resp.json().get("trades", [])


def _to_rfc3339(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_candle(raw: dict) -> Candle:
    mid = raw["mid"]
    time_str = raw["time"]
    # OANDA returns nanosecond precision; datetime.fromisoformat wants <=6.
    if "." in time_str:
        head, frac = time_str.split(".", 1)
        frac = frac.rstrip("Z")[:6]
        time_str = f"{head}.{frac}+00:00"
    else:
        time_str = time_str.replace("Z", "+00:00")
    return Candle(
        time=datetime.fromisoformat(time_str),
        open=float(mid["o"]),
        high=float(mid["h"]),
        low=float(mid["l"]),
        close=float(mid["c"]),
        volume=int(raw.get("volume", 0)),
    )
