from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from app.backtest_lab import indicators as ind
from app.backtest_lab.engine import (
    PIP,
    BacktestMetrics,
    Trade,
    candles_to_frame,
    compute_entry_signal,
    compute_metrics,
    run_backtest,
    simulate_trades,
)
from app.backtest_lab.schema import (
    AtrParams,
    AtrStop,
    EmaEntry,
    EmaParams,
    ExitConfig,
    RsiEntry,
    RsiParams,
    StrategyConfig,
)
from app.data_hub.models import Candle


UTC = timezone.utc


def make_candles(closes: list[float], start: datetime, step_minutes: int = 15) -> list[Candle]:
    candles = []
    t = start
    for c in closes:
        candles.append(
            Candle(time=t, open=c, high=c + 0.0002, low=c - 0.0002, close=c, volume=100)
        )
        t += timedelta(minutes=step_minutes)
    return candles


def ema_trend_config(fast=3, slow=6) -> StrategyConfig:
    return StrategyConfig(
        agent="Trend",
        timeframe="M15",
        entry=EmaEntry(params=EmaParams(fast=fast, slow=slow), rule="fast_cross_above_slow"),
        exit=ExitConfig(
            stop_loss=AtrStop(params=AtrParams(period=5, multiple=1.5)),
            take_profit=AtrStop(params=AtrParams(period=5, multiple=3.0)),
        ),
    )


# ---------------------------------------------------------------------------
# Schema: whitelist enforcement
# ---------------------------------------------------------------------------


class TestSchemaWhitelist:
    def test_valid_ema_strategy_parses(self):
        cfg = ema_trend_config()
        assert cfg.entry.indicator == "EMA"

    def test_unknown_indicator_rejected(self):
        with pytest.raises(ValidationError):
            StrategyConfig.model_validate(
                {
                    "agent": "Trend",
                    "timeframe": "M15",
                    "entry": {"indicator": "MACD", "params": {}, "rule": "whatever"},
                    "exit": {
                        "stop_loss": {"type": "ATR", "params": {"period": 14, "multiple": 1.5}},
                        "take_profit": {"type": "ATR", "params": {"period": 14, "multiple": 3.0}},
                    },
                }
            )

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            StrategyConfig.model_validate(
                {
                    "agent": "Trend",
                    "timeframe": "M15",
                    "entry": {
                        "indicator": "EMA",
                        "params": {"fast": 20, "slow": 50},
                        "rule": "fast_cross_above_slow",
                    },
                    "exit": {
                        "stop_loss": {"type": "ATR", "params": {"period": 14, "multiple": 1.5}},
                        "take_profit": {"type": "ATR", "params": {"period": 14, "multiple": 3.0}},
                    },
                    "leverage": 500,  # not part of the schema
                }
            )

    def test_out_of_range_params_rejected(self):
        with pytest.raises(ValidationError):
            RsiParams(period=1, oversold=30, overbought=70)  # period must be > 1


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------


class TestIndicators:
    def test_ema_converges_toward_constant_series(self):
        close = pd.Series([1.1] * 50)
        result = ind.ema(close, period=10)
        assert result.iloc[-1] == pytest.approx(1.1, abs=1e-9)

    def test_rsi_is_100_for_strictly_increasing_series(self):
        close = pd.Series(np.linspace(1.0, 1.1, 30))
        result = ind.rsi(close, period=14)
        assert result.iloc[-1] > 95

    def test_rsi_is_0_for_strictly_decreasing_series(self):
        close = pd.Series(np.linspace(1.1, 1.0, 30))
        result = ind.rsi(close, period=14)
        assert result.iloc[-1] < 5

    def test_atr_is_zero_for_flat_candles(self):
        n = 30
        df = pd.DataFrame({"high": [1.1] * n, "low": [1.1] * n, "close": [1.1] * n})
        result = ind.atr(df["high"], df["low"], df["close"], period=14)
        assert result.iloc[-1] == pytest.approx(0.0, abs=1e-9)

    def test_bollinger_bands_widen_with_volatility(self):
        close = pd.Series([1.1, 1.1, 1.1, 1.3, 0.9, 1.1, 1.1, 1.1, 1.1, 1.1])
        lower, mid, upper = ind.bollinger_bands(close, period=5, std_dev=2)
        assert (upper - lower).iloc[4] > 0


# ---------------------------------------------------------------------------
# Signal generation
# ---------------------------------------------------------------------------


class TestSignals:
    def test_ema_cross_above_produces_long_signal(self):
        # flat then sharp rally -> fast EMA crosses above slow EMA
        closes = [1.1000] * 10 + [1.1000 + i * 0.0010 for i in range(1, 15)]
        candles = make_candles(closes, datetime(2026, 1, 5, tzinfo=UTC))
        df = candles_to_frame(candles)
        cfg = ema_trend_config(fast=3, slow=8)

        signal = compute_entry_signal(df, cfg)
        assert (signal == 1).any()
        assert not (signal == -1).any()  # rule only fires long signals


# ---------------------------------------------------------------------------
# Trade simulation & metrics
# ---------------------------------------------------------------------------


class TestSimulateTrades:
    def test_uptrend_produces_winning_long_trades(self):
        closes = [1.1000] * 10 + [round(1.1000 + i * 0.0015, 5) for i in range(1, 40)]
        candles = make_candles(closes, datetime(2026, 1, 5, tzinfo=UTC))
        cfg = ema_trend_config(fast=3, slow=8)
        df = candles_to_frame(candles)

        trades = simulate_trades(df, cfg, spread_pips=0.5, commission_pips=0.0)
        assert len(trades) >= 1
        assert all(t.direction == 1 for t in trades)
        assert sum(t.pips for t in trades) > 0

    def test_flat_market_produces_no_trades(self):
        closes = [1.1000] * 60
        candles = make_candles(closes, datetime(2026, 1, 5, tzinfo=UTC))
        cfg = ema_trend_config(fast=3, slow=8)
        df = candles_to_frame(candles)

        trades = simulate_trades(df, cfg)
        assert trades == []

    def test_spread_and_commission_reduce_pips(self):
        closes = [1.1000] * 10 + [round(1.1000 + i * 0.0015, 5) for i in range(1, 40)]
        candles = make_candles(closes, datetime(2026, 1, 5, tzinfo=UTC))
        cfg = ema_trend_config(fast=3, slow=8)
        df = candles_to_frame(candles)

        cheap = simulate_trades(df, cfg, spread_pips=0.1, commission_pips=0.0)
        expensive = simulate_trades(df, cfg, spread_pips=5.0, commission_pips=2.0)
        assert sum(t.pips for t in cheap) > sum(t.pips for t in expensive)


class TestMetrics:
    def test_empty_trades_gives_zeroed_metrics(self):
        m = compute_metrics([])
        assert m == BacktestMetrics(sharpe=0.0, max_drawdown_pct=0.0, win_rate=0.0, trade_count=0, total_pips=0.0)

    def test_all_winning_trades_gives_full_win_rate(self):
        t = datetime(2026, 1, 5, tzinfo=UTC)
        trades = [
            Trade(entry_time=t, exit_time=t, direction=1, entry_price=1.1, exit_price=1.101, pips=10, outcome="win")
            for _ in range(5)
        ]
        m = compute_metrics(trades)
        assert m.win_rate == 1.0
        assert m.trade_count == 5
        assert m.total_pips == pytest.approx(50.0)

    def test_drawdown_detected_after_losses_following_gains(self):
        t = datetime(2026, 1, 5, tzinfo=UTC)
        pips_sequence = [20, 20, -15, -15, 20]
        trades = [
            Trade(
                entry_time=t,
                exit_time=t,
                direction=1,
                entry_price=1.1,
                exit_price=1.1,
                pips=p,
                outcome="win" if p > 0 else "loss",
            )
            for p in pips_sequence
        ]
        m = compute_metrics(trades)
        # peak was 40, dropped to 10 -> 75% drawdown off that peak
        assert m.max_drawdown_pct == pytest.approx(0.75, abs=1e-6)

    def test_win_rate_matches_losing_trade_ratio(self):
        t = datetime(2026, 1, 5, tzinfo=UTC)
        trades = [
            Trade(entry_time=t, exit_time=t, direction=1, entry_price=1.1, exit_price=1.1, pips=p, outcome="win" if p > 0 else "loss")
            for p in [10, -10, 10, -10, 10]
        ]
        m = compute_metrics(trades)
        assert m.win_rate == pytest.approx(0.6)


class TestWalkForwardBacktest:
    def test_split_produces_train_and_test_metrics(self):
        closes = [1.1000] * 10 + [round(1.1000 + i * 0.0012, 5) for i in range(1, 80)]
        candles = make_candles(closes, datetime(2026, 1, 5, tzinfo=UTC))
        cfg = ema_trend_config(fast=3, slow=8)

        result = run_backtest(candles, cfg, spread_pips=0.5, commission_pips=0.0, train_fraction=0.7)
        assert isinstance(result.train, BacktestMetrics)
        assert isinstance(result.test, BacktestMetrics)
        assert result.train.trade_count + result.test.trade_count == len(result.trades)

    def test_empty_candles_returns_zeroed_result(self):
        cfg = ema_trend_config()
        result = run_backtest([], cfg)
        assert result.trades == []
        assert result.train.trade_count == 0
        assert result.test.trade_count == 0
