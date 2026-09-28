"""Promotion gate: which backtested strategies are allowed onto the
OANDA practice account (AGENTS.md section 6).
"""
from __future__ import annotations

from app.backtest_lab.engine import BacktestMetrics

MIN_SHARPE = 1.0
MAX_DRAWDOWN_PCT = 0.10
MIN_TRADE_COUNT = 50


def passes_promotion_bar(test_metrics: BacktestMetrics) -> bool:
    """Promotion is judged on the out-of-sample (test) split only —
    in-sample (train) performance proves nothing about live edge."""
    return (
        test_metrics.sharpe > MIN_SHARPE
        and test_metrics.max_drawdown_pct < MAX_DRAWDOWN_PCT
        and test_metrics.trade_count >= MIN_TRADE_COUNT
    )
