from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.backtest_lab.engine import BacktestMetrics, BacktestResult
from app.backtest_lab.schema import (
    AtrParams,
    AtrStop,
    EmaEntry,
    EmaParams,
    ExitConfig,
    StrategyConfig,
)
from app.data_hub.cache import CandleCache
from app.data_hub.models import Candle
from app.data_hub.service import DataHub
from app.library.repository import Library
from app.main_tower import orchestrator as orch_module
from app.main_tower.allocation import allocate_capital
from app.main_tower.api import create_app
from app.main_tower.orchestrator import AgentActivity, MainTower
from app.news_tower.calendar import NewsCalendar
from app.paper_park.executor import PaperPark
from app.research_lab.service import ResearchLab
from app.risk_vault.vault import RiskVault

UTC = timezone.utc

VALID_EMA_JSON = """
{
  "agent": "Trend",
  "version": 1,
  "timeframe": "M15",
  "entry": {"indicator": "EMA", "params": {"fast": 20, "slow": 50}, "rule": "fast_cross_above_slow"},
  "exit": {
    "stop_loss": {"type": "ATR", "params": {"period": 14, "multiple": 1.5}},
    "take_profit": {"type": "ATR", "params": {"period": 14, "multiple": 3.0}}
  },
  "filters": [],
  "notes": "Initial proposal."
}
"""


class FakeClaudeClient:
    def __init__(self, response: str) -> None:
        self.response = response

    def complete(self, system: str, user_prompt: str, max_tokens: int = 1024) -> str:
        return self.response


class FakeOandaCandleSource:
    def __init__(self, candles: list[Candle]) -> None:
        self._candles = candles

    def get_candles(self, instrument, granularity, count=500, from_time=None, to_time=None):
        return self._candles[-count:]


class FakeOandaOrderClient:
    def __init__(self) -> None:
        self.orders: list[dict] = []

    def place_market_order(self, instrument, units, stop_loss_price, take_profit_price):
        self.orders.append(
            {"instrument": instrument, "units": units, "stop_loss_price": stop_loss_price, "take_profit_price": take_profit_price}
        )
        return {"orderFillTransaction": {"tradeOpened": {"tradeID": "fake-1"}}}


def make_candles(closes: list[float], start: datetime, step_minutes: int = 15) -> list[Candle]:
    candles = []
    t = start
    for c in closes:
        candles.append(Candle(time=t, open=c, high=c + 0.0002, low=c - 0.0002, close=c, volume=100))
        t += timedelta(minutes=step_minutes)
    return candles


def rallying_candles() -> list[Candle]:
    closes = [1.1000] * 15 + [round(1.1000 + i * 0.0020, 5) for i in range(1, 6)]
    all_candles = make_candles(closes, datetime(2026, 1, 5, 8, 0, tzinfo=UTC))
    return all_candles[:16]


def trend_config() -> StrategyConfig:
    return StrategyConfig(
        agent="Trend",
        timeframe="M15",
        entry=EmaEntry(params=EmaParams(fast=3, slow=8), rule="fast_cross_above_slow"),
        exit=ExitConfig(
            stop_loss=AtrStop(params=AtrParams(period=5, multiple=1.5)),
            take_profit=AtrStop(params=AtrParams(period=5, multiple=3.0)),
        ),
    )


@pytest.fixture()
def library(tmp_path) -> Library:
    return Library(database_url=f"sqlite:///{tmp_path / 'test.db'}")


def build_tower(
    library: Library, candles: list[Candle], claude_response: str = VALID_EMA_JSON
) -> tuple[MainTower, FakeOandaOrderClient, RiskVault]:
    cache = CandleCache(db_path=":memory:")
    data_hub = DataHub(client=FakeOandaCandleSource(candles), cache=cache)
    vault = RiskVault(kill_switch_env_var="TEST_MAIN_TOWER_KILL")
    calendar = NewsCalendar([])
    orders_client = FakeOandaOrderClient()
    paper_park = PaperPark(oanda_client=orders_client, risk_vault=vault, library=library, news_calendar=calendar)
    research_lab = ResearchLab(client=FakeClaudeClient(claude_response), library=library)

    tower = MainTower(
        research_lab=research_lab,
        paper_park=paper_park,
        data_hub=data_hub,
        library=library,
        risk_vault=vault,
    )
    return tower, orders_client, vault


# ---------------------------------------------------------------------------
# Allocation
# ---------------------------------------------------------------------------


class TestAllocateCapital:
    def test_allocates_proportional_to_positive_sharpe(self):
        result = allocate_capital(1000.0, {"A": 2.0, "B": 1.0, "C": None})
        assert result["A"] == pytest.approx(666.667, abs=0.01)
        assert result["B"] == pytest.approx(333.333, abs=0.01)
        assert result["C"] == 0.0

    def test_falls_back_to_equal_split_when_no_positive_sharpe(self):
        result = allocate_capital(900.0, {"A": None, "B": -0.5, "C": 0.0})
        assert result == {"A": 300.0, "B": 300.0, "C": 300.0}

    def test_single_agent_gets_everything(self):
        assert allocate_capital(500.0, {"A": 1.2}) == {"A": 500.0}


# ---------------------------------------------------------------------------
# Research cycle
# ---------------------------------------------------------------------------


class TestRunResearchCycle:
    def test_promotes_strategy_when_backtest_passes(self, library: Library, monkeypatch):
        tower, _orders, vault = build_tower(library, candles=[])
        vault.register_agent("Trend", starting_equity=10_000.0)

        good = BacktestMetrics(sharpe=1.5, max_drawdown_pct=0.05, win_rate=0.6, trade_count=60, total_pips=300)
        fake_result = BacktestResult(train=good, test=good, trades=[])
        monkeypatch.setattr(orch_module, "run_backtest", lambda candles, config, **kw: fake_result)

        config = tower.run_research_cycle("Trend")

        assert config is not None
        assert tower.active_strategies["Trend"] is config
        latest = library.get_latest_backtest("Trend")
        assert latest["passed_promotion_bar"] is True
        assert tower.status_for("Trend") == AgentActivity.IDLE

    def test_does_not_promote_when_backtest_fails_bar(self, library: Library, monkeypatch):
        tower, _orders, vault = build_tower(library, candles=[])
        vault.register_agent("Trend", starting_equity=10_000.0)

        bad = BacktestMetrics(sharpe=0.2, max_drawdown_pct=0.2, win_rate=0.4, trade_count=10, total_pips=-50)
        fake_result = BacktestResult(train=bad, test=bad, trades=[])
        monkeypatch.setattr(orch_module, "run_backtest", lambda candles, config, **kw: fake_result)

        config = tower.run_research_cycle("Trend")

        assert config is None
        assert "Trend" not in tower.active_strategies
        assert library.get_latest_backtest("Trend")["passed_promotion_bar"] is False

    def test_rejected_llm_response_skips_backtest_entirely(self, library: Library, monkeypatch):
        tower, _orders, vault = build_tower(library, candles=[], claude_response="not json at all")
        vault.register_agent("Trend", starting_equity=10_000.0)

        def fail_if_called(*args, **kwargs):
            raise AssertionError("run_backtest should not be called for a rejected proposal")

        monkeypatch.setattr(orch_module, "run_backtest", fail_if_called)

        config = tower.run_research_cycle("Trend")
        assert config is None
        assert "Trend" not in tower.active_strategies


# ---------------------------------------------------------------------------
# Trade cycle
# ---------------------------------------------------------------------------


class TestRunTradeCycle:
    def test_no_active_strategy_returns_none(self, library: Library):
        tower, orders, vault = build_tower(library, candles=[])
        vault.register_agent("Trend", starting_equity=10_000.0)

        assert tower.run_trade_cycle("Trend") is None
        assert orders.orders == []

    def test_places_trade_when_signal_present(self, library: Library):
        tower, orders, vault = build_tower(library, candles=rallying_candles())
        vault.register_agent("Trend", starting_equity=10_000.0)
        tower.active_strategies["Trend"] = trend_config()

        decision = tower.run_trade_cycle("Trend")

        assert decision is not None
        assert decision.should_trade is True
        assert len(orders.orders) == 1
        assert tower.status_for("Trend") == AgentActivity.IDLE


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


class TestStatus:
    def test_frozen_overrides_idle_activity(self, library: Library):
        tower, _orders, vault = build_tower(library, candles=[])
        vault.register_agent("Trend", starting_equity=10_000.0)
        vault.update_equity("Trend", new_equity=8_000.0)  # >10% drawdown

        assert tower.status_for("Trend") == AgentActivity.FROZEN

    def test_unregistered_agent_defaults_to_idle(self, library: Library):
        tower, _orders, _vault = build_tower(library, candles=[])
        assert tower.status_for("Ghost") == AgentActivity.IDLE


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


class TestApi:
    def test_health(self, library: Library):
        tower, *_ = build_tower(library, candles=[])
        client = TestClient(create_app(tower))
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_status_lists_all_three_agents(self, library: Library):
        tower, *_ = build_tower(library, candles=[])
        for name in ("Trend", "Reverter", "Breaker"):
            tower.risk_vault.register_agent(name, starting_equity=10_000.0)
        client = TestClient(create_app(tower))

        body = client.get("/api/status").json()
        assert set(body["agents"].keys()) == {"Trend", "Reverter", "Breaker"}
        assert body["kill_switch_active"] is False

    def test_kill_switch_toggle_roundtrip(self, library: Library):
        tower, *_ = build_tower(library, candles=[])
        client = TestClient(create_app(tower))

        assert client.post("/api/kill-switch/activate").json() == {"active": True}
        assert client.get("/api/kill-switch").json() == {"active": True}
        assert client.post("/api/kill-switch/deactivate").json() == {"active": False}

    def test_agent_detail_unknown_agent_404(self, library: Library):
        tower, *_ = build_tower(library, candles=[])
        client = TestClient(create_app(tower))
        assert client.get("/api/agents/NotReal").status_code == 404

    def test_agent_detail_known_agent(self, library: Library):
        tower, *_ = build_tower(library, candles=[])
        tower.risk_vault.register_agent("Trend", starting_equity=10_000.0)
        library.log_decision("Trend", {"a": 1}, reasoning="test reasoning")
        client = TestClient(create_app(tower))

        body = client.get("/api/agents/Trend").json()
        assert body["agent"] == "Trend"
        assert len(body["decisions"]) == 1
        assert body["decisions"][0]["reasoning"] == "test reasoning"

    def test_leaderboard_empty_by_default(self, library: Library):
        tower, *_ = build_tower(library, candles=[])
        client = TestClient(create_app(tower))
        assert client.get("/api/leaderboard").json() == []

    def test_unfreeze_agent(self, library: Library):
        tower, *_ = build_tower(library, candles=[])
        tower.risk_vault.register_agent("Trend", starting_equity=10_000.0)
        tower.risk_vault.update_equity("Trend", new_equity=8_000.0)
        client = TestClient(create_app(tower))

        resp = client.post("/api/agents/Trend/unfreeze")
        assert resp.status_code == 200
        assert resp.json()["status"] == "idle"
        assert tower.risk_vault.can_trade("Trend") is True

    def test_unfreeze_unregistered_agent_404(self, library: Library):
        tower, *_ = build_tower(library, candles=[])
        client = TestClient(create_app(tower))
        assert client.post("/api/agents/Trend/unfreeze").status_code == 404
