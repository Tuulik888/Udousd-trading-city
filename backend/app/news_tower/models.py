from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Impact(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


_IMPACT_RANK = {Impact.LOW: 0, Impact.MEDIUM: 1, Impact.HIGH: 2}


def impact_rank(impact: Impact) -> int:
    return _IMPACT_RANK[impact]


@dataclass(frozen=True, slots=True)
class EconomicEvent:
    time: datetime  # UTC
    currency: str  # "USD", "EUR", ...
    impact: Impact
    name: str
