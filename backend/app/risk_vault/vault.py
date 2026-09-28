"""The Risk Vault — hardcoded, deterministic risk enforcement.

No LLM agent and no strategy config can alter anything in this module.
It is the single gate between "a strategy wants to trade" and an order
reaching OANDA. See AGENTS.md section 2 for the rules this implements
and `backend/tests/test_risk_vault.py` for the contract this must keep
satisfying.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from urllib.parse import urlparse

MAX_RISK_PER_TRADE = 0.005  # 0.5% of equity
MAX_DAILY_LOSS = 0.02  # 2% of equity, measured from the day's starting equity
MAX_DRAWDOWN = 0.10  # 10% off the peak equity -> freeze

_ALLOWED_OANDA_HOST = "api-fxpractice.oanda.com"

UTC = timezone.utc


class RiskViolation(Exception):
    """Raised whenever an action would breach a hardcoded risk rule."""


class AgentStatus(str, Enum):
    ACTIVE = "active"
    DAILY_HALTED = "daily_halted"
    FROZEN = "frozen"


@dataclass
class AgentRiskState:
    agent_id: str
    starting_equity: float
    peak_equity: float
    current_equity: float
    daily_start_equity: float
    daily_date: date
    status: AgentStatus = AgentStatus.ACTIVE
    freeze_reason: str | None = None


class RiskVault:
    def __init__(self, kill_switch_env_var: str = "TRADING_KILL_SWITCH") -> None:
        self._agents: dict[str, AgentRiskState] = {}
        self._kill_switch_env_var = kill_switch_env_var
        self._dashboard_kill_switch = False

    # ------------------------------------------------------------------
    # Kill switch
    # ------------------------------------------------------------------

    def activate_kill_switch(self) -> None:
        self._dashboard_kill_switch = True

    def deactivate_kill_switch(self) -> None:
        self._dashboard_kill_switch = False

    def is_kill_switch_active(self) -> bool:
        env_val = os.environ.get(self._kill_switch_env_var, "")
        env_active = env_val.strip().lower() in {"1", "true", "yes", "on"}
        return self._dashboard_kill_switch or env_active

    # ------------------------------------------------------------------
    # Agent lifecycle
    # ------------------------------------------------------------------

    def register_agent(
        self, agent_id: str, starting_equity: float, now: datetime | None = None
    ) -> AgentRiskState:
        now = now or datetime.now(UTC)
        state = AgentRiskState(
            agent_id=agent_id,
            starting_equity=starting_equity,
            peak_equity=starting_equity,
            current_equity=starting_equity,
            daily_start_equity=starting_equity,
            daily_date=now.astimezone(UTC).date(),
        )
        self._agents[agent_id] = state
        return state

    def get_state(self, agent_id: str) -> AgentRiskState:
        return self._agents[agent_id]

    def unfreeze_agent(self, agent_id: str) -> None:
        """Manual human action — a frozen (drawdown-breached) agent never
        unfreezes itself."""
        state = self._agents[agent_id]
        state.status = AgentStatus.ACTIVE
        state.freeze_reason = None
        # Give it a clean slate: today's baseline resets, and the peak
        # resets to current equity so it isn't instantly re-frozen by the
        # same drawdown that just got it frozen.
        state.peak_equity = state.current_equity
        state.daily_start_equity = state.current_equity

    # ------------------------------------------------------------------
    # Per-trade risk cap
    # ------------------------------------------------------------------

    def max_position_units(
        self, agent_id: str, stop_loss_distance_price: float, value_per_unit: float = 1.0
    ) -> float:
        state = self._agents[agent_id]
        max_risk_amount = state.current_equity * MAX_RISK_PER_TRADE
        risk_per_unit = stop_loss_distance_price * value_per_unit
        if risk_per_unit <= 0:
            raise RiskViolation("stop_loss_distance_price must be > 0")
        return max_risk_amount / risk_per_unit

    def validate_trade_risk(
        self,
        agent_id: str,
        stop_loss_distance_price: float,
        units: float,
        value_per_unit: float = 1.0,
    ) -> None:
        state = self._agents[agent_id]
        proposed_risk = abs(units) * stop_loss_distance_price * value_per_unit
        max_risk_amount = state.current_equity * MAX_RISK_PER_TRADE
        if proposed_risk > max_risk_amount + 1e-9:
            risk_pct = proposed_risk / state.current_equity
            raise RiskViolation(
                f"Trade risks {risk_pct:.4%} of equity, exceeding the "
                f"{MAX_RISK_PER_TRADE:.2%} per-trade cap"
            )

    # ------------------------------------------------------------------
    # Equity tracking -> daily loss halt / drawdown freeze
    # ------------------------------------------------------------------

    def update_equity(self, agent_id: str, new_equity: float, now: datetime | None = None) -> None:
        state = self._agents[agent_id]
        now = now or datetime.now(UTC)
        today = now.astimezone(UTC).date()

        if today != state.daily_date:
            state.daily_date = today
            state.daily_start_equity = state.current_equity
            if state.status == AgentStatus.DAILY_HALTED:
                state.status = AgentStatus.ACTIVE

        state.current_equity = new_equity
        state.peak_equity = max(state.peak_equity, new_equity)

        drawdown = (state.peak_equity - new_equity) / state.peak_equity if state.peak_equity > 0 else 0.0
        if drawdown > MAX_DRAWDOWN and state.status != AgentStatus.FROZEN:
            state.status = AgentStatus.FROZEN
            state.freeze_reason = (
                f"Drawdown {drawdown:.2%} exceeded the {MAX_DRAWDOWN:.0%} limit "
                f"(peak={state.peak_equity:.2f}, current={new_equity:.2f})"
            )
            return

        if state.status == AgentStatus.FROZEN:
            return  # stays frozen regardless of daily P&L until manually unfrozen

        daily_loss = (state.daily_start_equity - new_equity) / state.daily_start_equity if state.daily_start_equity > 0 else 0.0
        if daily_loss > MAX_DAILY_LOSS:
            state.status = AgentStatus.DAILY_HALTED
        elif state.status == AgentStatus.DAILY_HALTED:
            state.status = AgentStatus.ACTIVE

    # ------------------------------------------------------------------
    # Trading gate
    # ------------------------------------------------------------------

    def can_trade(self, agent_id: str) -> bool:
        if self.is_kill_switch_active():
            return False
        state = self._agents.get(agent_id)
        if state is None:
            return False
        return state.status == AgentStatus.ACTIVE

    def assert_can_trade(self, agent_id: str) -> None:
        if self.is_kill_switch_active():
            raise RiskViolation("Global kill switch is active — all trading halted")
        state = self._agents.get(agent_id)
        if state is None:
            raise RiskViolation(f"Unknown agent: {agent_id!r}")
        if state.status == AgentStatus.FROZEN:
            raise RiskViolation(f"Agent {agent_id!r} is frozen: {state.freeze_reason}")
        if state.status == AgentStatus.DAILY_HALTED:
            raise RiskViolation(f"Agent {agent_id!r} hit its daily loss limit for today")

    # ------------------------------------------------------------------
    # OANDA practice-only enforcement
    # ------------------------------------------------------------------

    @staticmethod
    def assert_practice_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != _ALLOWED_OANDA_HOST:
            raise RiskViolation(
                f"Refusing non-practice OANDA URL: {url!r}. "
                f"Only https://{_ALLOWED_OANDA_HOST} is permitted."
            )
