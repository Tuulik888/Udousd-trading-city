"""main_tower: the orchestrator tying every building together.

Runs the research cycle (propose -> backtest -> promote-or-not) and the
trade cycle (evaluate the currently-promoted config against the latest
candle) for a single agent at a time, and tracks each agent's
dashboard-visible activity status.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.backtest_lab.engine import run_backtest
from app.backtest_lab.schema import StrategyConfig
from app.data_hub.service import DataHub
from app.library.repository import Library
from app.paper_park.executor import PaperPark, TradeDecision
from app.paper_park.promotion import passes_promotion_bar
from app.research_lab.service import ResearchLab
from app.risk_vault.vault import AgentStatus, RiskVault


class AgentActivity(str, Enum):
    IDLE = "idle"
    THINKING = "thinking"
    BACKTESTING = "backtesting"
    TRADING = "trading"
    FROZEN = "frozen"


@dataclass
class MainTower:
    research_lab: ResearchLab
    paper_park: PaperPark
    data_hub: DataHub
    library: Library
    risk_vault: RiskVault
    instrument: str = "EUR_USD"
    backtest_candle_count: int = 500
    trade_candle_count: int = 200

    active_strategies: dict[str, StrategyConfig] = field(default_factory=dict)
    _activity: dict[str, AgentActivity] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Dashboard-visible status
    # ------------------------------------------------------------------

    def status_for(self, agent_name: str) -> AgentActivity:
        try:
            state = self.risk_vault.get_state(agent_name)
        except KeyError:
            return self._activity.get(agent_name, AgentActivity.IDLE)
        if state.status == AgentStatus.FROZEN:
            return AgentActivity.FROZEN
        return self._activity.get(agent_name, AgentActivity.IDLE)

    # ------------------------------------------------------------------
    # Research cycle: propose -> backtest -> promote or not
    # ------------------------------------------------------------------

    def run_research_cycle(self, agent_name: str) -> StrategyConfig | None:
        self._activity[agent_name] = AgentActivity.THINKING
        try:
            proposal = self.research_lab.propose_strategy(agent_name, past_results=self._past_results(agent_name))
            if proposal.strategy_config is None:
                return None

            self._activity[agent_name] = AgentActivity.BACKTESTING
            candles = self.data_hub.get_candles(
                self.instrument, proposal.strategy_config.timeframe.value, count=self.backtest_candle_count
            )
            result = run_backtest(candles, proposal.strategy_config)
            passed = passes_promotion_bar(result.test)
            self.library.log_backtest(
                agent_name, result.train, result.test, passed_promotion_bar=passed, decision_id=proposal.decision_id
            )

            if passed:
                self.active_strategies[agent_name] = proposal.strategy_config
                return proposal.strategy_config
            return None
        finally:
            self._activity[agent_name] = AgentActivity.IDLE

    # ------------------------------------------------------------------
    # Trade cycle: evaluate the promoted config against the latest candle
    # ------------------------------------------------------------------

    def run_trade_cycle(self, agent_name: str) -> TradeDecision | None:
        config = self.active_strategies.get(agent_name)
        if config is None:
            return None

        self._activity[agent_name] = AgentActivity.TRADING
        try:
            candles = self.data_hub.get_candles(self.instrument, config.timeframe.value, count=self.trade_candle_count)
            return self.paper_park.evaluate_and_trade(agent_name, config, candles)
        finally:
            self._activity[agent_name] = AgentActivity.IDLE

    # ------------------------------------------------------------------

    def _past_results(self, agent_name: str) -> list[dict]:
        latest = self.library.get_latest_backtest(agent_name)
        if latest is None:
            return []
        decisions = self.library.get_decisions(agent_name, limit=1)
        strategy_config = decisions[0]["strategy_config"] if decisions else {}
        return [
            {
                "strategy_config": strategy_config,
                "sharpe_test": latest["sharpe_test"],
                "max_dd_test": latest["max_dd_test"],
                "win_rate_test": latest["win_rate_test"],
                "trade_count_test": latest["trade_count_test"],
                "pips_test": latest["pips_test"],
                "passed_promotion_bar": latest["passed_promotion_bar"],
            }
        ]
