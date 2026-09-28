from __future__ import annotations

import pytest

from app.research_lab.claude_client import ClaudeClientProtocol
from app.research_lab.personas import PERSONAS, build_user_prompt
from app.research_lab.schema import StrategyProposalError, extract_json_object, parse_strategy_config
from app.research_lab.service import ResearchLab
from app.library.repository import Library


VALID_EMA_JSON = """
{
  "agent": "Trend",
  "version": 1,
  "timeframe": "M15",
  "entry": {"indicator": "EMA", "params": {"fast": 20, "slow": 50}, "rule": "fast_cross_above_slow"},
  "exit": {
    "stop_loss": {"type": "ATR", "params": {"period": 14, "multiple": 1.5}},
    "take_profit": {"type": "ATR", "params": {"period": 14, "multiple": 3.0}}
  },
  "filters": ["news_blackout"],
  "notes": "Widened EMA slow period after last cycle's whipsaws."
}
"""


class FakeClaudeClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict] = []

    def complete(self, system: str, user_prompt: str, max_tokens: int = 1024) -> str:
        self.calls.append({"system": system, "user_prompt": user_prompt, "max_tokens": max_tokens})
        return self.response


@pytest.fixture()
def library(tmp_path) -> Library:
    return Library(database_url=f"sqlite:///{tmp_path / 'test.db'}")


# ---------------------------------------------------------------------------
# Schema parsing (extraction + validation)
# ---------------------------------------------------------------------------


class TestParseStrategyConfig:
    def test_parses_plain_json(self):
        config = parse_strategy_config(VALID_EMA_JSON)
        assert config.entry.indicator == "EMA"
        assert config.agent == "Trend"

    def test_parses_json_wrapped_in_markdown_fence(self):
        wrapped = f"Here you go:\n```json\n{VALID_EMA_JSON}\n```\nHope that helps!"
        config = parse_strategy_config(wrapped)
        assert config.entry.indicator == "EMA"

    def test_rejects_non_json_text(self):
        with pytest.raises(StrategyProposalError):
            parse_strategy_config("I refuse to output JSON today.")

    def test_rejects_indicator_outside_whitelist(self):
        bad = VALID_EMA_JSON.replace('"EMA"', '"MACD"')
        with pytest.raises(StrategyProposalError):
            parse_strategy_config(bad)

    def test_rejects_malformed_json(self):
        with pytest.raises(StrategyProposalError):
            parse_strategy_config("{not valid json,,,}")

    def test_extract_json_object_finds_embedded_object(self):
        text = 'prefix noise { "a": 1 } trailing noise'
        assert extract_json_object(text) == {"a": 1}


# ---------------------------------------------------------------------------
# Personas
# ---------------------------------------------------------------------------


class TestPersonas:
    def test_all_three_agents_defined(self):
        assert set(PERSONAS.keys()) == {"Trend", "Reverter", "Breaker"}

    def test_user_prompt_with_no_history(self):
        prompt = build_user_prompt("Trend", [])
        assert "no past backtest results" in prompt.lower()

    def test_user_prompt_summarizes_past_results(self):
        past = [
            {
                "strategy_config": {"entry": {"indicator": "EMA"}},
                "sharpe_test": 1.4,
                "max_dd_test": 0.06,
                "win_rate_test": 0.55,
                "trade_count_test": 62,
                "pips_test": 320.0,
                "passed_promotion_bar": True,
            }
        ]
        prompt = build_user_prompt("Trend", past)
        assert "1.4" in prompt
        assert "passed_promotion_bar=True" in prompt


# ---------------------------------------------------------------------------
# ResearchLab service
# ---------------------------------------------------------------------------


class TestResearchLab:
    def test_valid_proposal_is_parsed_and_logged(self, library: Library):
        client = FakeClaudeClient(VALID_EMA_JSON)
        lab = ResearchLab(client=client, library=library)

        result = lab.propose_strategy("Trend")

        assert result.error is None
        assert result.strategy_config is not None
        assert result.strategy_config.entry.indicator == "EMA"

        decisions = library.get_decisions("Trend")
        assert len(decisions) == 1
        assert "Widened EMA slow period" in decisions[0]["reasoning"]

    def test_invalid_proposal_is_rejected_and_logged(self, library: Library):
        client = FakeClaudeClient("not json at all")
        lab = ResearchLab(client=client, library=library)

        result = lab.propose_strategy("Reverter")

        assert result.strategy_config is None
        assert result.error is not None
        decisions = library.get_decisions("Reverter")
        assert len(decisions) == 1
        assert "REJECTED" in decisions[0]["reasoning"]

    def test_unknown_agent_raises(self, library: Library):
        client = FakeClaudeClient(VALID_EMA_JSON)
        lab = ResearchLab(client=client, library=library)
        with pytest.raises(ValueError):
            lab.propose_strategy("NotAnAgent")

    def test_persona_system_prompt_sent_to_client(self, library: Library):
        client = FakeClaudeClient(VALID_EMA_JSON)
        lab = ResearchLab(client=client, library=library)

        lab.propose_strategy("Trend")

        assert len(client.calls) == 1
        assert "Trend" in client.calls[0]["system"]
        assert "EMA" in client.calls[0]["system"]

    def test_past_results_are_passed_into_the_prompt(self, library: Library):
        client = FakeClaudeClient(VALID_EMA_JSON)
        lab = ResearchLab(client=client, library=library)
        past = [{"strategy_config": {}, "sharpe_test": 0.4, "max_dd_test": 0.2, "win_rate_test": 0.3, "trade_count_test": 12, "pips_test": -50.0, "passed_promotion_bar": False}]

        lab.propose_strategy("Trend", past_results=past)

        assert "0.4" in client.calls[0]["user_prompt"]
