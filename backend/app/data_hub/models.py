"""Shared data types for data_hub."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Candle:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
