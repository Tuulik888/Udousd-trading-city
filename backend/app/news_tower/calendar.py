"""Economic calendar blackout — blocks trading 30 minutes before/after
high-impact USD/EUR events (AGENTS.md section 3).

`NewsCalendar` holds whatever events were loaded into it; how those
events get loaded is deliberately separate (see `source.py`) so the
blackout logic itself needs no network access and is fully unit
testable.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .models import EconomicEvent, Impact, impact_rank

DEFAULT_BLACKOUT_MINUTES = 30
DEFAULT_CURRENCIES = ("USD", "EUR")
DEFAULT_MIN_IMPACT = Impact.HIGH


class NewsCalendar:
    def __init__(self, events: list[EconomicEvent] | None = None) -> None:
        self._events: list[EconomicEvent] = list(events or [])

    def load_events(self, events: list[EconomicEvent]) -> None:
        self._events = list(events)

    def add_event(self, event: EconomicEvent) -> None:
        self._events.append(event)

    def is_blackout(
        self,
        at: datetime,
        window_minutes: int = DEFAULT_BLACKOUT_MINUTES,
        currencies: tuple[str, ...] = DEFAULT_CURRENCIES,
        min_impact: Impact = DEFAULT_MIN_IMPACT,
    ) -> bool:
        return self._blackout_event(at, window_minutes, currencies, min_impact) is not None

    def blackout_reason(
        self,
        at: datetime,
        window_minutes: int = DEFAULT_BLACKOUT_MINUTES,
        currencies: tuple[str, ...] = DEFAULT_CURRENCIES,
        min_impact: Impact = DEFAULT_MIN_IMPACT,
    ) -> str | None:
        event = self._blackout_event(at, window_minutes, currencies, min_impact)
        if event is None:
            return None
        return f"{event.currency} {event.impact.value}-impact event '{event.name}' at {event.time.isoformat()}"

    def _blackout_event(
        self,
        at: datetime,
        window_minutes: int,
        currencies: tuple[str, ...],
        min_impact: Impact,
    ) -> EconomicEvent | None:
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        threshold_rank = impact_rank(min_impact)
        window = timedelta(minutes=window_minutes)
        for event in self._events:
            if event.currency not in currencies:
                continue
            if impact_rank(event.impact) < threshold_rank:
                continue
            event_time = event.time if event.time.tzinfo else event.time.replace(tzinfo=timezone.utc)
            if abs(at - event_time) <= window:
                return event
        return None
