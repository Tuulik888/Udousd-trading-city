"""Deterministic backtest engine.

Takes a validated `StrategyConfig` (never raw LLM text) and a candle
history, and produces trade-by-trade + aggregate metrics with a
chronological train/test (walk-forward) split. Spread and a flat
per-trade commission are modeled as real trading costs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

import numpy as np
import pandas as pd

from app.data_hub.models import Candle

from . import indicators as ind
from .schema import (
    BollingerEntry,
    EmaEntry,
    RsiEntry,
    SessionBreakoutEntry,
    StrategyConfig,
)

PIP = 0.0001  # EUR_USD pip size
TRADING_DAYS_PER_YEAR = 252


# ---------------------------------------------------------------------------
# Data prep
# ---------------------------------------------------------------------------


def candles_to_frame(candles: list[Candle]) -> pd.DataFrame:
    if not candles:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame(
        {
            "open": [c.open for c in candles],
            "high": [c.high for c in candles],
            "low": [c.low for c in candles],
            "close": [c.close for c in candles],
            "volume": [c.volume for c in candles],
        },
        index=pd.DatetimeIndex([c.time for c in candles], name="time"),
    )
    return df.sort_index()


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------


def compute_entry_signal(df: pd.DataFrame, config: StrategyConfig) -> pd.Series:
    """Returns a Series of {0, 1, -1} per bar: 1 = long entry signal,
    -1 = short entry signal, 0 = no signal."""
    entry = config.entry
    signal = pd.Series(0, index=df.index, dtype=int)

    if isinstance(entry, EmaEntry):
        fast = ind.ema(df["close"], entry.params.fast)
        slow = ind.ema(df["close"], entry.params.slow)
        cross_up = (fast.shift(1) <= slow.shift(1)) & (fast > slow)
        cross_down = (fast.shift(1) >= slow.shift(1)) & (fast < slow)
        if entry.rule == "fast_cross_above_slow":
            signal[cross_up] = 1
        else:
            signal[cross_down] = -1

    elif isinstance(entry, RsiEntry):
        rsi_series = ind.rsi(df["close"], entry.params.period)
        if entry.rule == "cross_above_oversold":
            crossed = (rsi_series.shift(1) <= entry.params.oversold) & (
                rsi_series > entry.params.oversold
            )
            signal[crossed] = 1
        else:
            crossed = (rsi_series.shift(1) >= entry.params.overbought) & (
                rsi_series < entry.params.overbought
            )
            signal[crossed] = -1

    elif isinstance(entry, BollingerEntry):
        lower, _mid, upper = ind.bollinger_bands(
            df["close"], entry.params.period, entry.params.std_dev
        )
        if entry.rule == "touch_lower_band":
            signal[df["low"] <= lower] = 1
        else:
            signal[df["high"] >= upper] = -1

    elif isinstance(entry, SessionBreakoutEntry):
        levels = ind.session_high_low(
            df, entry.params.session_start_hour, entry.params.session_end_hour
        )
        closed = levels["session_closed"]
        if entry.rule == "break_above_high":
            breakout = closed & (df["close"] > levels["session_high"])
            first_of_day = breakout & ~breakout.shift(1, fill_value=False)
            signal[first_of_day] = 1
        else:
            breakout = closed & (df["close"] < levels["session_low"])
            first_of_day = breakout & ~breakout.shift(1, fill_value=False)
            signal[first_of_day] = -1

    else:  # pragma: no cover - schema whitelist makes this unreachable
        raise ValueError(f"Unsupported entry indicator: {entry!r}")

    return signal


def compute_stop_distance(df: pd.DataFrame, rule) -> pd.Series:
    from .schema import AtrStop, FixedPipsStop

    if isinstance(rule, AtrStop):
        return ind.atr(df["high"], df["low"], df["close"], rule.params.period) * rule.params.multiple
    if isinstance(rule, FixedPipsStop):
        return pd.Series(rule.params.pips * PIP, index=df.index)
    raise ValueError(f"Unsupported stop rule: {rule!r}")  # pragma: no cover


# ---------------------------------------------------------------------------
# Trade simulation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Trade:
    entry_time: datetime
    exit_time: datetime
    direction: Literal[1, -1]
    entry_price: float
    exit_price: float
    pips: float
    outcome: Literal["win", "loss"]


def simulate_trades(
    df: pd.DataFrame,
    config: StrategyConfig,
    spread_pips: float = 1.2,
    commission_pips: float = 0.2,
) -> list[Trade]:
    if df.empty:
        return []

    signal = compute_entry_signal(df, config)
    sl_distance = compute_stop_distance(df, config.exit.stop_loss)
    tp_distance = compute_stop_distance(df, config.exit.take_profit)
    spread = spread_pips * PIP

    trades: list[Trade] = []
    in_position = False
    direction = 0
    entry_price = sl_price = tp_price = 0.0
    entry_time: datetime | None = None

    times = df.index.to_pydatetime()
    opens = df["open"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    sig = signal.to_numpy()
    sl_arr = sl_distance.to_numpy()
    tp_arr = tp_distance.to_numpy()

    for i in range(len(df)):
        if in_position:
            hit_sl = (lows[i] <= sl_price) if direction == 1 else (highs[i] >= sl_price)
            hit_tp = (highs[i] >= tp_price) if direction == 1 else (lows[i] <= tp_price)
            if hit_sl or hit_tp:
                # conservative: if both could have hit in the same bar, count the loss
                exit_price = sl_price if hit_sl else tp_price
                raw_pips = (exit_price - entry_price) * direction / PIP
                net_pips = raw_pips - spread_pips - commission_pips
                trades.append(
                    Trade(
                        entry_time=entry_time,
                        exit_time=times[i],
                        direction=direction,
                        entry_price=entry_price,
                        exit_price=exit_price,
                        pips=net_pips,
                        outcome="win" if net_pips > 0 else "loss",
                    )
                )
                in_position = False
                continue

        if not in_position and sig[i] != 0 and not np.isnan(sl_arr[i]):
            direction = int(sig[i])
            entry_price = opens[i] + (spread / 2 if direction == 1 else -spread / 2)
            sl_price = entry_price - direction * sl_arr[i]
            tp_price = entry_price + direction * tp_arr[i]
            entry_time = times[i]
            in_position = True

    return trades


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BacktestMetrics:
    sharpe: float
    max_drawdown_pct: float
    win_rate: float
    trade_count: int
    total_pips: float


def compute_metrics(trades: list[Trade]) -> BacktestMetrics:
    if not trades:
        return BacktestMetrics(sharpe=0.0, max_drawdown_pct=0.0, win_rate=0.0, trade_count=0, total_pips=0.0)

    pips = np.array([t.pips for t in trades], dtype=float)
    wins = pips > 0
    win_rate = float(wins.sum() / len(pips))
    total_pips = float(pips.sum())

    mean = pips.mean()
    std = pips.std(ddof=1) if len(pips) > 1 else 0.0
    per_trade_sharpe = (mean / std) if std > 0 else 0.0
    sharpe = float(per_trade_sharpe * np.sqrt(len(pips)))

    # Drawdown as a fraction of the running peak equity (in pips). Before
    # the equity curve ever turns positive there's no meaningful "peak" to
    # measure a percentage against, so those bars contribute 0.
    equity_curve = np.cumsum(pips)
    running_peak = np.maximum.accumulate(equity_curve)
    with np.errstate(divide="ignore", invalid="ignore"):
        drawdown_pct = np.where(
            running_peak > 0, (running_peak - equity_curve) / running_peak, 0.0
        )
    max_drawdown_pct = float(np.max(drawdown_pct)) if len(drawdown_pct) else 0.0

    return BacktestMetrics(
        sharpe=sharpe,
        max_drawdown_pct=max_drawdown_pct,
        win_rate=win_rate,
        trade_count=len(trades),
        total_pips=total_pips,
    )


# ---------------------------------------------------------------------------
# Walk-forward backtest
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BacktestResult:
    train: BacktestMetrics
    test: BacktestMetrics
    trades: list[Trade] = field(default_factory=list)


def run_backtest(
    candles: list[Candle],
    config: StrategyConfig,
    spread_pips: float = 1.2,
    commission_pips: float = 0.2,
    train_fraction: float = 0.7,
) -> BacktestResult:
    df = candles_to_frame(candles)
    trades = simulate_trades(df, config, spread_pips=spread_pips, commission_pips=commission_pips)

    if df.empty:
        split_time = None
    else:
        split_idx = int(len(df) * train_fraction)
        split_idx = min(max(split_idx, 0), len(df) - 1)
        split_time = df.index[split_idx]

    if split_time is None:
        train_trades, test_trades = [], []
    else:
        train_trades = [t for t in trades if t.entry_time < split_time]
        test_trades = [t for t in trades if t.entry_time >= split_time]

    return BacktestResult(
        train=compute_metrics(train_trades),
        test=compute_metrics(test_trades),
        trades=trades,
    )
