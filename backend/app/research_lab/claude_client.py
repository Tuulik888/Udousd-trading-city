"""Thin wrapper around the Anthropic SDK.

Kept minimal and behind a `complete(system, user_prompt) -> str`
interface so `ResearchLab` can be tested against a fake implementation
of the same shape, with no network access and no API key required.
"""
from __future__ import annotations

from typing import Protocol

import anthropic


class ClaudeClientProtocol(Protocol):
    def complete(self, system: str, user_prompt: str, max_tokens: int = 1024) -> str: ...


class ClaudeClient:
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-5") -> None:
        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def complete(self, system: str, user_prompt: str, max_tokens: int = 1024) -> str:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return "".join(block.text for block in response.content if block.type == "text")
