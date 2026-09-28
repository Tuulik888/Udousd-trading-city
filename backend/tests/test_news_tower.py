from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.news_tower.calendar import NewsCalendar
from app.news_tower.models import EconomicEvent, Impact
from app.news_tower.source import InMemoryCalendarSource, StaticJsonCalendarSource

UTC = timezone.utc


def event(minutes_offset: int, currency="USD", impact=Impact.HIGH, name="NFP", base=None):
    base = base or datetime(2026, 1, 5, 13, 30, tzinfo=UTC)
    return EconomicEvent(time=base + timedelta(minutes=minutes_offset), currency=currency, impact=impact, name=name)


class TestBlackoutWindow:
    def test_blocks_within_30_minutes_before_and_after_high_impact(self):
        cal = NewsCalendar([event(0)])
        base = datetime(2026, 1, 5, 13, 30, tzinfo=UTC)

        assert cal.is_blackout(base - timedelta(minutes=29)) is True
        assert cal.is_blackout(base) is True
        assert cal.is_blackout(base + timedelta(minutes=29)) is True

    def test_allows_trading_outside_the_window(self):
        cal = NewsCalendar([event(0)])
        base = datetime(2026, 1, 5, 13, 30, tzinfo=UTC)

        assert cal.is_blackout(base - timedelta(minutes=31)) is False
        assert cal.is_blackout(base + timedelta(minutes=31)) is False

    def test_ignores_low_and_medium_impact_events_by_default(self):
        cal = NewsCalendar([event(0, impact=Impact.LOW), event(0, impact=Impact.MEDIUM)])
        base = datetime(2026, 1, 5, 13, 30, tzinfo=UTC)
        assert cal.is_blackout(base) is False

    def test_ignores_currencies_outside_usd_eur_by_default(self):
        cal = NewsCalendar([event(0, currency="JPY")])
        base = datetime(2026, 1, 5, 13, 30, tzinfo=UTC)
        assert cal.is_blackout(base) is False

    def test_eur_high_impact_also_blocks(self):
        cal = NewsCalendar([event(0, currency="EUR")])
        base = datetime(2026, 1, 5, 13, 30, tzinfo=UTC)
        assert cal.is_blackout(base) is True

    def test_no_events_never_blackout(self):
        cal = NewsCalendar([])
        assert cal.is_blackout(datetime(2026, 1, 5, 13, 30, tzinfo=UTC)) is False

    def test_blackout_reason_describes_the_event(self):
        cal = NewsCalendar([event(0, name="ECB Rate Decision", currency="EUR")])
        reason = cal.blackout_reason(datetime(2026, 1, 5, 13, 30, tzinfo=UTC))
        assert reason is not None
        assert "ECB Rate Decision" in reason
        assert "EUR" in reason

    def test_naive_datetime_treated_as_utc(self):
        cal = NewsCalendar([event(0)])
        naive = datetime(2026, 1, 5, 13, 30)  # no tzinfo
        assert cal.is_blackout(naive) is True


class TestCalendarSources:
    def test_static_json_source_loads_events(self, tmp_path):
        path = tmp_path / "calendar.json"
        path.write_text(
            json.dumps(
                [
                    {"time": "2026-01-05T13:30:00Z", "currency": "USD", "impact": "high", "name": "NFP"},
                ]
            )
        )
        source = StaticJsonCalendarSource(path)
        events = source.load()
        assert len(events) == 1
        assert events[0].name == "NFP"
        assert events[0].impact == Impact.HIGH

    def test_static_json_source_missing_file_returns_empty(self, tmp_path):
        source = StaticJsonCalendarSource(tmp_path / "missing.json")
        assert source.load() == []

    def test_in_memory_source_roundtrips(self):
        events = [event(0)]
        source = InMemoryCalendarSource(events)
        assert source.load() == events
