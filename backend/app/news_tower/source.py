"""Pluggable sources for populating a NewsCalendar.

MVP ships a static JSON-file source (hand-maintained or produced by a
periodic scraper job) so the blackout logic has no hard dependency on a
particular calendar API/key. Swap in a live source later by implementing
the same `load() -> list[EconomicEvent]` shape.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from .models import EconomicEvent, Impact


class CalendarSource(Protocol):
    def load(self) -> list[EconomicEvent]: ...


class StaticJsonCalendarSource:
    """Loads events from a JSON file shaped like:

    [
      {"time": "2026-01-05T13:30:00Z", "currency": "USD", "impact": "high", "name": "NFP"}
    ]
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> list[EconomicEvent]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text())
        events = []
        for item in raw:
            time_str = item["time"].replace("Z", "+00:00")
            events.append(
                EconomicEvent(
                    time=datetime.fromisoformat(time_str).astimezone(timezone.utc),
                    currency=item["currency"],
                    impact=Impact(item["impact"]),
                    name=item["name"],
                )
            )
        return events


class InMemoryCalendarSource:
    def __init__(self, events: list[EconomicEvent] | None = None) -> None:
        self._events = events or []

    def load(self) -> list[EconomicEvent]:
        return list(self._events)
