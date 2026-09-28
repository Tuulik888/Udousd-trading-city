"""Turns raw LLM text into a validated StrategyConfig, or rejects it.

This is the actual enforcement point of AGENTS.md section 1: whatever
the model says, if it doesn't parse as JSON matching the indicator
whitelist in `backtest_lab.schema.StrategyConfig`, it never becomes a
strategy the backtester or executor will touch.
"""
from __future__ import annotations

import json
import re

from pydantic import ValidationError

from app.backtest_lab.schema import StrategyConfig

_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


class StrategyProposalError(Exception):
    """Raised when an LLM response can't be turned into a valid StrategyConfig."""


def extract_json_object(text: str) -> dict:
    text = text.strip()
    fence_match = _FENCE_RE.search(text)
    if fence_match:
        candidate = fence_match.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise StrategyProposalError("No JSON object found in LLM response")
        candidate = text[start : end + 1]

    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise StrategyProposalError(f"Invalid JSON in LLM response: {exc}") from exc


def parse_strategy_config(raw_text: str) -> StrategyConfig:
    data = extract_json_object(raw_text)
    try:
        return StrategyConfig.model_validate(data)
    except ValidationError as exc:
        raise StrategyProposalError(f"Strategy config failed schema validation: {exc}") from exc
