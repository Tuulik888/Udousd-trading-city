"""Strategy config schema — the ONLY contract between an LLM agent and
the deterministic backtester/executor.

Every field is validated against a closed set of indicators (AGENTS.md
section 1). An LLM response that doesn't parse against this schema is
rejected before it ever reaches `backtest_lab.engine` — see
`research_lab.schema.parse_strategy_config`.
"""
from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class Timeframe(str, Enum):
    M15 = "M15"
    H1 = "H1"


# ---------------------------------------------------------------------------
# Entry rules (indicator whitelist: EMA, RSI, BOLLINGER, SESSION_BREAKOUT)
# ---------------------------------------------------------------------------


class EmaParams(BaseModel):
    fast: int = Field(gt=0, le=200)
    slow: int = Field(gt=0, le=400)


class EmaEntry(BaseModel):
    indicator: Literal["EMA"] = "EMA"
    params: EmaParams
    rule: Literal["fast_cross_above_slow", "fast_cross_below_slow"]


class RsiParams(BaseModel):
    period: int = Field(gt=1, le=100)
    oversold: float = Field(gt=0, lt=100, default=30)
    overbought: float = Field(gt=0, lt=100, default=70)


class RsiEntry(BaseModel):
    indicator: Literal["RSI"] = "RSI"
    params: RsiParams
    rule: Literal["cross_above_oversold", "cross_below_overbought"]


class BollingerParams(BaseModel):
    period: int = Field(gt=1, le=200)
    std_dev: float = Field(gt=0, le=5)


class BollingerEntry(BaseModel):
    indicator: Literal["BOLLINGER"] = "BOLLINGER"
    params: BollingerParams
    rule: Literal["touch_lower_band", "touch_upper_band"]


class SessionBreakoutParams(BaseModel):
    session_start_hour: int = Field(ge=0, le=23, default=0)
    session_end_hour: int = Field(ge=0, le=23, default=7)


class SessionBreakoutEntry(BaseModel):
    indicator: Literal["SESSION_BREAKOUT"] = "SESSION_BREAKOUT"
    params: SessionBreakoutParams
    rule: Literal["break_above_high", "break_below_low"]


EntryRule = Annotated[
    Union[EmaEntry, RsiEntry, BollingerEntry, SessionBreakoutEntry],
    Field(discriminator="indicator"),
]


# ---------------------------------------------------------------------------
# Stop-loss / take-profit rules (ATR-based, or fixed pips)
# ---------------------------------------------------------------------------


class AtrParams(BaseModel):
    period: int = Field(gt=1, le=100, default=14)
    multiple: float = Field(gt=0, le=20)


class AtrStop(BaseModel):
    type: Literal["ATR"] = "ATR"
    params: AtrParams


class FixedPipsParams(BaseModel):
    pips: float = Field(gt=0, le=500)


class FixedPipsStop(BaseModel):
    type: Literal["FIXED_PIPS"] = "FIXED_PIPS"
    params: FixedPipsParams


StopRule = Annotated[Union[AtrStop, FixedPipsStop], Field(discriminator="type")]


class ExitConfig(BaseModel):
    stop_loss: StopRule
    take_profit: StopRule


# ---------------------------------------------------------------------------
# Top-level strategy config
# ---------------------------------------------------------------------------


class StrategyConfig(BaseModel):
    agent: str
    version: int = 1
    timeframe: Timeframe
    entry: EntryRule
    exit: ExitConfig
    filters: list[str] = Field(default_factory=list)
    notes: str = ""

    model_config = {"extra": "forbid"}
