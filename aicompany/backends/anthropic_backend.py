"""Anthropic (Claude) LLM backend."""
from __future__ import annotations

import os

import anthropic

from aicompany.llm_backend import register_backend


class AnthropicBackend:
    """LLM backend using the Anthropic Messages API."""

    def __init__(self) -> None:
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY is not set. "
                "Export it or add it to .env before using the Anthropic backend."
            )
        self._client = anthropic.Anthropic()

    def call(self, system: str, user: str, max_tokens: int, model: str) -> str:
        response = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return response.content[0].text


register_backend("anthropic", AnthropicBackend)
