from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.backtest_lab.engine import BacktestMetrics
from app.backtest_lab.schema import (
    AtrParams,
    AtrStop,
    EmaEntry,
    EmaParams,
    ExitConfig,
    StrategyConfig,
)
from app.data_hub.models import Candle
from app.library.repository import Library
from app.news_tower.calendar import NewsCalendar
from app.news_tower.models import EconomicEvent, Impact
from app.paper_park.executor import PaperPark
from app.paper_park.promotion import passes_promotion_bar
from app.risk_vault.vault import RiskVault

UTC = timezone.utc


class FakeOandaClient:
    def __init__(self) -> None:
        self.orders: list[dict] = []

    def place_market_order(self, instrument, units, stop_loss_price, take_profit_price):
        self.orders.append(
            {
                "instrument": instrument,
                "units": units,
                "stop_loss_price": stop_loss_price,
                "take_profit_price": take_profit_price,
            }
        )
        return {"orderFillTransaction": {"tradeOpened": {"tradeID": "fake-trade-1"}}}


@pytest.fixture()
def library(tmp_path) -> Library:
    return Library(database_url=f"sqlite:///{tmp_path / 'test.db'}")


def make_candles(closes: list[float], start: datetime, step_minutes: int = 15) -> list[Candle]:
    candles = []
    t = start
    for c in closes:
        candles.append(Candle(time=t, open=c, high=c + 0.0002, low=c - 0.0002, close=c, volume=100))
        t += timedelta(minutes=step_minutes)
    return candles


def rallying_candles() -> list[Candle]:
    # Flat, then a rally whose fast/slow EMA cross lands exactly on the
    # LAST candle, so evaluate_and_trade sees a live entry signal "now".
    closes = [1.1000] * 15 + [round(1.1000 + i * 0.0020, 5) for i in range(1, 6)]
    all_candles = make_candles(closes, datetime(2026, 1, 5, 8, 0, tzinfo=UTC))
    return all_candles[:16]


def flat_candles() -> list[Candle]:
    return make_candles([1.1000] * 30, datetime(2026, 1, 5, 8, 0, tzinfo=UTC))


def trend_config() -> StrategyConfig:
    return StrategyConfig(
        agent="Trend",
        timeframe="M15",
        entry=EmaEntry(params=EmaParams(fast=3, slow=8), rule="fast_cross_above_slow"),
        exit=ExitConfig(
            stop_loss=AtrStop(params=AtrParams(period=5, multiple=1.5)),
            take_profit=AtrStop(params=AtrParams(period=5, multiple=3.0)),
        ),
        filters=["news_blackout"],
        notes="test config",
    )


def make_park(library: Library, oanda=None, vault=None, calendar=None) -> tuple[PaperPark, FakeOandaClient, RiskVault]:
    oanda = oanda or FakeOandaClient()
    vault = vault or RiskVault(kill_switch_env_var="TEST_KILL_SWITCH_PP")
    calendar = calendar if calendar is not None else NewsCalendar([])
    park = PaperPark(oanda_client=oanda, risk_vault=vault, library=library, news_calendar=calendar)
    return park, oanda, vault


class TestPromotionBar:
    def test_passes_when_all_three_conditions_met(self):
        m = BacktestMetrics(sharpe=1.5, max_drawdown_pct=0.05, win_rate=0.6, trade_count=60, total_pips=200)
        assert passes_promotion_bar(m) is True

    def test_fails_on_low_sharpe(self):
        m = BacktestMetrics(sharpe=0.9, max_drawdown_pct=0.05, win_rate=0.6, trade_count=60, total_pips=200)
        assert passes_promotion_bar(m) is False

    def test_fails_on_high_drawdown(self):
        m = BacktestMetrics(sharpe=1.5, max_drawdown_pct=0.12, win_rate=0.6, trade_count=60, total_pips=200)
        assert passes_promotion_bar(m) is False

    def test_fails_on_too_few_trades(self):
        m = BacktestMetrics(sharpe=1.5, max_drawdown_pct=0.05, win_rate=0.6, trade_count=40, total_pips=200)
        assert passes_promotion_bar(m) is False


class TestPaperParkGating:
    def test_kill_switch_blocks_trade(self, library: Library):
        park, oanda, vault = make_park(library)
        vault.register_agent("Trend", starting_equity=10_000.0)
        vault.activate_kill_switch()

        decision = park.evaluate_and_trade("Trend", trend_config(), rallying_candles())

        assert decision.should_trade is False
        assert "Risk Vault" in decision.reason
        assert oanda.orders == []

    def test_frozen_agent_blocks_trade(self, library: Library):
        park, oanda, vault = make_park(library)
        vault.register_agent("Trend", starting_equity=10_000.0)
        vault.update_equity("Trend", new_equity=8_500.0)  # >10% drawdown -> frozen

        decision = park.evaluate_and_trade("Trend", trend_config(), rallying_candles())

        assert decision.should_trade is False
        assert oanda.orders == []

    def test_news_blackout_blocks_trade_when_filter_present(self, library: Library):
        now = datetime(2026, 1, 5, 8, 0, tzinfo=UTC) + timedelta(minutes=15 * 28)
        blackout_event = EconomicEvent(time=now, currency="USD", impact=Impact.HIGH, name="NFP")
        calendar = NewsCalendar([blackout_event])
        park, oanda, vault = make_park(library, calendar=calendar)
        vault.register_agent("Trend", starting_equity=10_000.0)

        decision = park.evaluate_and_trade("Trend", trend_config(), rallying_candles(), now=now)

        assert decision.should_trade is False
        assert "news blackout" in decision.reason
        assert oanda.orders == []

    def test_news_blackout_ignored_when_filter_absent(self, library: Library):
        now = datetime(2026, 1, 5, 8, 0, tzinfo=UTC) + timedelta(minutes=15 * 28)
        blackout_event = EconomicEvent(time=now, currency="USD", impact=Impact.HIGH, name="NFP")
        calendar = NewsCalendar([blackout_event])
        park, oanda, vault = make_park(library, calendar=calendar)
        vault.register_agent("Trend", starting_equity=10_000.0)

        cfg = trend_config()
        cfg.filters = []  # no news_blackout filter
        decision = park.evaluate_and_trade("Trend", cfg, rallying_candles(), now=now)

        assert decision.should_trade is True

    def test_existing_open_position_blocks_new_trade(self, library: Library):
        park, oanda, vault = make_park(library)
        vault.register_agent("Trend", starting_equity=10_000.0)
        library.log_trade_open(
            "Trend",
            instrument="EUR_USD",
            direction=1,
            units=1000,
            entry_price=1.1,
            entry_time=datetime(2026, 1, 5, tzinfo=UTC),
        )

        decision = park.evaluate_and_trade("Trend", trend_config(), rallying_candles())

        assert decision.should_trade is False
        assert "already has an open position" in decision.reason
        assert oanda.orders == []

    def test_no_signal_on_flat_market(self, library: Library):
        park, oanda, vault = make_park(library)
        vault.register_agent("Trend", starting_equity=10_000.0)

        decision = park.evaluate_and_trade("Trend", trend_config(), flat_candles())

        assert decision.should_trade is False
        assert oanda.orders == []


class TestPaperParkExecution:
    def test_successful_trade_places_order_and_logs(self, library: Library):
        park, oanda, vault = make_park(library)
        vault.register_agent("Trend", starting_equity=10_000.0)

        decision = park.evaluate_and_trade("Trend", trend_config(), rallying_candles())

        assert decision.should_trade is True
        assert decision.direction == 1
        assert len(oanda.orders) == 1
        assert oanda.orders[0]["instrument"] == "EUR_USD"
        assert oanda.orders[0]["units"] > 0  # long

        open_trades = library.get_open_trades("Trend")
        assert len(open_trades) == 1
        assert open_trades[0]["oanda_trade_id"] == "fake-trade-1"

    def test_order_units_respect_risk_cap(self, library: Library):
        park, oanda, vault = make_park(library)
        vault.register_agent("Trend", starting_equity=10_000.0)

        park.evaluate_and_trade("Trend", trend_config(), rallying_candles())

        order = oanda.orders[0]
        entry_price = library.get_open_trades("Trend")[0]["entry_price"]
        sl_distance = abs(entry_price - order["stop_loss_price"])
        implied_risk = abs(order["units"]) * sl_distance
        max_allowed_risk = 10_000.0 * 0.005

        assert implied_risk <= max_allowed_risk + 1e-6
