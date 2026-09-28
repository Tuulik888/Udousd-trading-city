"""Tests for the Risk Vault — written before the implementation.

The Risk Vault is the only thing standing between an LLM-proposed
strategy and a real (practice-money) order. Every rule in AGENTS.md
section 2 must be covered here, and these tests must keep passing for
any future change to `app.risk_vault.vault`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from freezegun import freeze_time

from app.risk_vault.vault import (
    MAX_DAILY_LOSS,
    MAX_DRAWDOWN,
    MAX_RISK_PER_TRADE,
    AgentStatus,
    RiskVault,
    RiskViolation,
)


UTC = timezone.utc


def make_vault() -> RiskVault:
    return RiskVault(kill_switch_env_var="TRADING_KILL_SWITCH_TEST")


# --------------------------------------------------------------------------
# Per-trade risk cap (0.5% of equity)
# --------------------------------------------------------------------------


class TestPerTradeRiskCap:
    def test_max_position_units_respects_half_percent_risk(self):
        vault = make_vault()
        vault.register_agent("Trend", starting_equity=10_000.0)

        # 0.5% of 10,000 = 50 risk currency units available.
        # stop distance is 0.0025 price units, value per unit is 1.0 per
        # price-unit-of-move -> max units = 50 / 0.0025 = 20,000
        max_units = vault.max_position_units(
            "Trend", stop_loss_distance_price=0.0025, value_per_unit=1.0
        )
        assert max_units == pytest.approx(20_000.0)

    def test_validate_trade_risk_accepts_trade_within_cap(self):
        vault = make_vault()
        vault.register_agent("Trend", starting_equity=10_000.0)

        # risk = 15,000 * 0.0025 = 37.5 -> 0.375% < 0.5%, should not raise
        vault.validate_trade_risk(
            "Trend", stop_loss_distance_price=0.0025, units=15_000.0, value_per_unit=1.0
        )

    def test_validate_trade_risk_rejects_trade_over_cap(self):
        vault = make_vault()
        vault.register_agent("Trend", starting_equity=10_000.0)

        # risk = 25,000 * 0.0025 = 62.5 -> 0.625% > 0.5%, must raise
        with pytest.raises(RiskViolation):
            vault.validate_trade_risk(
                "Trend", stop_loss_distance_price=0.0025, units=25_000.0, value_per_unit=1.0
            )

    def test_validate_trade_risk_uses_current_equity_not_starting(self):
        vault = make_vault()
        vault.register_agent("Trend", starting_equity=10_000.0)
        vault.update_equity("Trend", new_equity=5_000.0)

        # 0.5% of 5,000 = 25. units=15,000 * 0.0025 = 37.5 -> now over cap.
        with pytest.raises(RiskViolation):
            vault.validate_trade_risk(
                "Trend", stop_loss_distance_price=0.0025, units=15_000.0, value_per_unit=1.0
            )

    def test_constant_matches_spec(self):
        assert MAX_RISK_PER_TRADE == pytest.approx(0.005)


# --------------------------------------------------------------------------
# Daily loss limit (2%)
# --------------------------------------------------------------------------


class TestDailyLossLimit:
    def test_agent_halted_after_daily_loss_breach(self):
        vault = make_vault()
        with freeze_time("2026-01-05 08:00:00"):
            vault.register_agent("Reverter", starting_equity=10_000.0)
            # lose 2.5% intraday
            vault.update_equity("Reverter", new_equity=9_750.0)

        assert vault.can_trade("Reverter") is False
        state = vault.get_state("Reverter")
        assert state.status == AgentStatus.DAILY_HALTED

    def test_daily_loss_halt_does_not_persist_to_next_day(self):
        vault = make_vault()
        with freeze_time("2026-01-05 08:00:00"):
            vault.register_agent("Reverter", starting_equity=10_000.0)
            vault.update_equity("Reverter", new_equity=9_750.0)
        assert vault.can_trade("Reverter") is False

        with freeze_time("2026-01-06 00:05:00"):
            # first equity update of the new UTC day resets the daily baseline
            vault.update_equity("Reverter", new_equity=9_750.0)
            assert vault.can_trade("Reverter") is True

    def test_daily_loss_exactly_at_threshold_does_not_halt(self):
        vault = make_vault()
        with freeze_time("2026-01-05 08:00:00"):
            vault.register_agent("Reverter", starting_equity=10_000.0)
            # exactly -2.0% loss
            vault.update_equity("Reverter", new_equity=9_800.0)
        assert vault.can_trade("Reverter") is True

    def test_constant_matches_spec(self):
        assert MAX_DAILY_LOSS == pytest.approx(0.02)


# --------------------------------------------------------------------------
# Drawdown limit (10%) -> freeze
# --------------------------------------------------------------------------


class TestDrawdownFreeze:
    def test_agent_frozen_after_drawdown_breach(self):
        vault = make_vault()
        vault.register_agent("Breaker", starting_equity=10_000.0)
        vault.update_equity("Breaker", new_equity=11_000.0)  # new peak
        vault.update_equity("Breaker", new_equity=9_850.0)  # 10.45% off peak

        state = vault.get_state("Breaker")
        assert state.status == AgentStatus.FROZEN
        assert vault.can_trade("Breaker") is False

    def test_drawdown_measured_from_peak_not_starting_equity(self):
        vault = make_vault()
        vault.register_agent("Breaker", starting_equity=10_000.0)
        vault.update_equity("Breaker", new_equity=12_000.0)  # peak
        # 10,900 is +9% vs starting equity but -9.17% off the 12,000 peak,
        # so it must NOT freeze yet.
        vault.update_equity("Breaker", new_equity=10_900.0)
        assert vault.can_trade("Breaker") is True

        # now breach 10% off the 12,000 peak (10,700 -> -10.83%)
        vault.update_equity("Breaker", new_equity=10_700.0)
        assert vault.get_state("Breaker").status == AgentStatus.FROZEN

    def test_frozen_agent_stays_frozen_across_days(self):
        vault = make_vault()
        with freeze_time("2026-01-05 08:00:00"):
            vault.register_agent("Breaker", starting_equity=10_000.0)
            vault.update_equity("Breaker", new_equity=8_900.0)  # 11% DD
        assert vault.can_trade("Breaker") is False

        with freeze_time("2026-01-06 08:00:00"):
            vault.update_equity("Breaker", new_equity=8_900.0)
            # unlike the daily halt, a freeze survives a new day
            assert vault.can_trade("Breaker") is False

    def test_frozen_agent_requires_manual_unfreeze(self):
        vault = make_vault()
        vault.register_agent("Breaker", starting_equity=10_000.0)
        vault.update_equity("Breaker", new_equity=8_900.0)
        assert vault.can_trade("Breaker") is False

        vault.unfreeze_agent("Breaker")
        assert vault.get_state("Breaker").status == AgentStatus.ACTIVE
        assert vault.can_trade("Breaker") is True

    def test_constant_matches_spec(self):
        assert MAX_DRAWDOWN == pytest.approx(0.10)


# --------------------------------------------------------------------------
# Global kill switch (env var OR dashboard button)
# --------------------------------------------------------------------------


class TestKillSwitch:
    def test_kill_switch_off_by_default(self, monkeypatch):
        monkeypatch.delenv("TRADING_KILL_SWITCH_TEST", raising=False)
        vault = make_vault()
        vault.register_agent("Trend", starting_equity=10_000.0)
        assert vault.is_kill_switch_active() is False
        assert vault.can_trade("Trend") is True

    def test_env_var_kill_switch_blocks_all_agents(self, monkeypatch):
        monkeypatch.setenv("TRADING_KILL_SWITCH_TEST", "true")
        vault = make_vault()
        vault.register_agent("Trend", starting_equity=10_000.0)
        vault.register_agent("Reverter", starting_equity=10_000.0)

        assert vault.is_kill_switch_active() is True
        assert vault.can_trade("Trend") is False
        assert vault.can_trade("Reverter") is False

    def test_dashboard_kill_switch_blocks_all_agents(self, monkeypatch):
        monkeypatch.delenv("TRADING_KILL_SWITCH_TEST", raising=False)
        vault = make_vault()
        vault.register_agent("Trend", starting_equity=10_000.0)

        vault.activate_kill_switch()
        assert vault.can_trade("Trend") is False

        vault.deactivate_kill_switch()
        assert vault.can_trade("Trend") is True

    def test_assert_can_trade_raises_with_reason_when_killed(self, monkeypatch):
        monkeypatch.delenv("TRADING_KILL_SWITCH_TEST", raising=False)
        vault = make_vault()
        vault.register_agent("Trend", starting_equity=10_000.0)
        vault.activate_kill_switch()

        with pytest.raises(RiskViolation, match="kill switch"):
            vault.assert_can_trade("Trend")


# --------------------------------------------------------------------------
# OANDA practice-only URL enforcement
# --------------------------------------------------------------------------


class TestPracticeOnlyUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "https://api-fxpractice.oanda.com",
            "https://api-fxpractice.oanda.com/v3/accounts/123/candles",
        ],
    )
    def test_practice_urls_allowed(self, url):
        RiskVault.assert_practice_url(url)  # must not raise

    @pytest.mark.parametrize(
        "url",
        [
            "https://api-fxtrade.oanda.com",
            "https://api-fxtrade.oanda.com/v3/accounts/123/orders",
            "http://api-fxtrade.oanda.com",
            "https://stream-fxtrade.oanda.com",
            "https://evil.example.com/api-fxpractice.oanda.com",
        ],
    )
    def test_live_or_untrusted_urls_hard_blocked(self, url):
        with pytest.raises(RiskViolation):
            RiskVault.assert_practice_url(url)


# --------------------------------------------------------------------------
# General agent lifecycle
# --------------------------------------------------------------------------


class TestAgentLifecycle:
    def test_unknown_agent_raises(self):
        vault = make_vault()
        with pytest.raises(KeyError):
            vault.get_state("Nope")

    def test_can_trade_false_for_unregistered_agent(self):
        vault = make_vault()
        assert vault.can_trade("Nope") is False

    def test_register_agent_sets_initial_state(self):
        vault = make_vault()
        state = vault.register_agent("Trend", starting_equity=10_000.0)
        assert state.status == AgentStatus.ACTIVE
        assert state.current_equity == 10_000.0
        assert state.peak_equity == 10_000.0
        assert state.daily_start_equity == 10_000.0
