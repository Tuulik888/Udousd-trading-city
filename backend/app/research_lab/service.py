"""research_lab: asks an agent's persona (via Claude) to propose or
refine its strategy config, validates the response, and logs the
decision (accepted or rejected) to the library.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.backtest_lab.schema import StrategyConfig
from app.library.repository import Library

from .claude_client import ClaudeClientProtocol
from .personas import PERSONAS, build_user_prompt
from .schema import StrategyProposalError, parse_strategy_config


@dataclass
class ProposalResult:
    agent_name: str
    strategy_config: StrategyConfig | None
    raw_response: str
    error: str | None
    decision_id: int


class ResearchLab:
    def __init__(self, client: ClaudeClientProtocol, library: Library) -> None:
        self.client = client
        self.library = library

    def propose_strategy(self, agent_name: str, past_results: list[dict] | None = None) -> ProposalResult:
        if agent_name not in PERSONAS:
            raise ValueError(f"Unknown agent persona: {agent_name!r}")

        persona = PERSONAS[agent_name]
        user_prompt = build_user_prompt(agent_name, past_results or [])
        raw = self.client.complete(system=persona["system_prompt"], user_prompt=user_prompt)

        try:
            config = parse_strategy_config(raw)
        except StrategyProposalError as exc:
            decision_id = self.library.log_decision(
                agent_name,
                {"rejected": True},
                reasoning=f"REJECTED: {exc}\n\nraw response:\n{raw}",
            )
            return ProposalResult(
                agent_name=agent_name,
                strategy_config=None,
                raw_response=raw,
                error=str(exc),
                decision_id=decision_id,
            )

        decision_id = self.library.log_decision(
            agent_name,
            config.model_dump(mode="json"),
            reasoning=config.notes or "(no notes provided)",
        )
        return ProposalResult(
            agent_name=agent_name,
            strategy_config=config,
            raw_response=raw,
            error=None,
            decision_id=decision_id,
        )
