from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.backtest_lab.engine import BacktestMetrics
from app.library.repository import Library

UTC = timezone.utc


@pytest.fixture()
def library(tmp_path) -> Library:
    db_path = tmp_path / "test.db"
    return Library(database_url=f"sqlite:///{db_path}")


class TestDecisions:
    def test_log_and_get_decision(self, library: Library):
        cfg = {"agent": "Trend", "timeframe": "M15"}
        library.log_decision("Trend", cfg, reasoning="EMA cross looked strong in backtest")

        decisions = library.get_decisions("Trend")
        assert len(decisions) == 1
        assert decisions[0]["strategy_config"] == cfg
        assert "EMA cross" in decisions[0]["reasoning"]

    def test_decisions_ordered_most_recent_first(self, library: Library):
        library.log_decision("Trend", {"v": 1})
        library.log_decision("Trend", {"v": 2})

        decisions = library.get_decisions("Trend")
        assert [d["strategy_config"]["v"] for d in decisions] == [2, 1]

    def test_decisions_scoped_per_agent(self, library: Library):
        library.log_decision("Trend", {"v": 1})
        library.log_decision("Reverter", {"v": 99})

        assert len(library.get_decisions("Trend")) == 1
        assert len(library.get_decisions("Reverter")) == 1


class TestBacktests:
    def test_log_and_get_latest_backtest(self, library: Library):
        train = BacktestMetrics(sharpe=1.5, max_drawdown_pct=0.05, win_rate=0.6, trade_count=80, total_pips=300.0)
        test = BacktestMetrics(sharpe=1.2, max_drawdown_pct=0.08, win_rate=0.55, trade_count=60, total_pips=150.0)

        library.log_backtest("Trend", train, test, passed_promotion_bar=True)
        latest = library.get_latest_backtest("Trend")

        assert latest is not None
        assert latest["sharpe_test"] == pytest.approx(1.2)
        assert latest["passed_promotion_bar"] is True
        assert latest["trade_count_test"] == 60

    def test_latest_backtest_none_when_no_runs(self, library: Library):
        assert library.get_latest_backtest("Unknown") is None

    def test_latest_backtest_returns_most_recent(self, library: Library):
        m1 = BacktestMetrics(sharpe=0.5, max_drawdown_pct=0.1, win_rate=0.4, trade_count=10, total_pips=10.0)
        m2 = BacktestMetrics(sharpe=1.8, max_drawdown_pct=0.05, win_rate=0.6, trade_count=55, total_pips=400.0)

        library.log_backtest("Trend", m1, m1, passed_promotion_bar=False)
        library.log_backtest("Trend", m2, m2, passed_promotion_bar=True)

        latest = library.get_latest_backtest("Trend")
        assert latest["sharpe_test"] == pytest.approx(1.8)


class TestTrades:
    def test_open_then_close_trade(self, library: Library):
        trade_id = library.log_trade_open(
            "Breaker",
            instrument="EUR_USD",
            direction=1,
            units=10_000,
            entry_price=1.1000,
            entry_time=datetime(2026, 1, 5, 8, 0, tzinfo=UTC),
            oanda_trade_id="abc123",
            reasoning="London breakout above Asian high",
        )

        open_trades = library.get_open_trades("Breaker")
        assert len(open_trades) == 1
        assert open_trades[0]["status"] == "open"

        library.log_trade_close(
            trade_id, exit_price=1.1050, exit_time=datetime(2026, 1, 5, 10, 0, tzinfo=UTC), pips=50.0
        )

        assert library.get_open_trades("Breaker") == []
        trades = library.get_trades("Breaker")
        assert trades[0]["status"] == "closed"
        assert trades[0]["pips"] == pytest.approx(50.0)

    def test_close_unknown_trade_raises(self, library: Library):
        with pytest.raises(KeyError):
            library.log_trade_close(999, exit_price=1.1, exit_time=datetime.now(UTC), pips=0.0)


class TestEquityCurveAndLeaderboard:
    def test_equity_curve_ordered_chronologically(self, library: Library):
        library.log_equity_snapshot("Trend", 10_000.0, at=datetime(2026, 1, 1, tzinfo=UTC))
        library.log_equity_snapshot("Trend", 10_150.0, at=datetime(2026, 1, 2, tzinfo=UTC))

        curve = library.get_equity_curve("Trend")
        assert [c["equity"] for c in curve] == [10_000.0, 10_150.0]

    def test_leaderboard_ranks_by_sharpe_not_pips(self, library: Library):
        high_sharpe_low_pips = BacktestMetrics(sharpe=2.0, max_drawdown_pct=0.05, win_rate=0.6, trade_count=60, total_pips=50.0)
        low_sharpe_high_pips = BacktestMetrics(sharpe=0.8, max_drawdown_pct=0.09, win_rate=0.5, trade_count=55, total_pips=900.0)

        library.log_backtest("Reverter", high_sharpe_low_pips, high_sharpe_low_pips, passed_promotion_bar=True)
        library.log_backtest("Breaker", low_sharpe_high_pips, low_sharpe_high_pips, passed_promotion_bar=True)

        board = library.get_leaderboard()
        assert [row["agent"] for row in board] == ["Reverter", "Breaker"]

    def test_leaderboard_handles_agents_with_no_backtest_yet(self, library: Library):
        library.get_or_create_agent("Trend")
        board = library.get_leaderboard()
        assert board[0]["agent"] == "Trend"
        assert board[0]["sharpe"] is None
