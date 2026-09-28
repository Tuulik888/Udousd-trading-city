"""Pure-function indicator implementations. Every strategy config's
`entry`/`exit` sections resolve to one of these — nothing else is
computable, which is what keeps the indicator whitelist enforceable.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(close: pd.Series, period: int) -> pd.Series:
    return close.ewm(span=period, adjust=False).mean()


def rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, float("nan"))
    result = 100 - (100 / (1 + rs))
    # avg_loss == 0: no losses in the lookback -> RSI is 100 (or 50 if
    # there were no gains either, i.e. a perfectly flat series).
    result = result.where(avg_loss != 0, np.where(avg_gain > 0, 100.0, 50.0))
    return pd.Series(result, index=close.index).fillna(50.0)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    prev_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(alpha=1 / period, adjust=False).mean()


def bollinger_bands(
    close: pd.Series, period: int, std_dev: float
) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    return lower, mid, upper


def session_high_low(
    df: pd.DataFrame, session_start_hour: int, session_end_hour: int
) -> pd.DataFrame:
    """For every bar, the prior/current session's high & low — e.g. the
    Asian range (00:00-07:00 UTC) that a London breakout strategy tests
    against once the session window has closed.
    """
    idx = df.index
    day_key = idx.normalize()
    in_session = (idx.hour >= session_start_hour) & (idx.hour < session_end_hour)

    session_df = df.loc[in_session]
    daily_high = session_df["high"].groupby(session_df.index.normalize()).max()
    daily_low = session_df["low"].groupby(session_df.index.normalize()).min()

    session_high = day_key.map(daily_high)
    session_low = day_key.map(daily_low)
    return pd.DataFrame(
        {
            "session_high": session_high.to_numpy(dtype=float),
            "session_low": session_low.to_numpy(dtype=float),
            "session_closed": ~in_session,
        },
        index=idx,
    )
