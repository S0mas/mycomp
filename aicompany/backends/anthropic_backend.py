"""Anthropic (Claude) LLM backend."""
from __future__ import annotations

import os

import anthropic

from aicompany import config
from aicompany.llm_backend import register_backend

# Per-call timeout in seconds. MCP calls involve many tool round-trips so we
# give them more time, but still cap to avoid silent 10-minute hangs.
_TIMEOUT_PLAIN = int(os.environ.get("AICOMPANY_API_TIMEOUT", "120"))
_TIMEOUT_MCP   = int(os.environ.get("AICOMPANY_API_TIMEOUT_MCP", "300"))


class AnthropicBackend:
    """LLM backend using the Anthropic Messages API.

    Uses client.beta.messages.create() with mcp-client-2025-04-04 when
    mcp_servers is non-empty; otherwise plain client.messages.create().
    """

    def __init__(self, mcp_servers: list[dict] | None = None) -> None:
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY is not set. "
                "Export it or add it to .env before using the Anthropic backend."
            )
        self._client = anthropic.Anthropic(timeout=_TIMEOUT_MCP)
        self._mcp_servers: list[dict] = (
            mcp_servers if mcp_servers is not None else config.MCP_SERVERS
        )

    def call(self, system: str, user: str, max_tokens: int, model: str) -> str:
        log = config.task_log.get()

        def _log(level: str, msg: str) -> None:
            if log:
                log(level, msg)

        if self._mcp_servers:
            _log("BACKEND", f"call model={model} max_tokens={max_tokens} mcp=True timeout={_TIMEOUT_MCP}s")
            response = self._client.beta.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                mcp_servers=self._mcp_servers,
                betas=["mcp-client-2025-04-04"],
                timeout=_TIMEOUT_MCP,
            )
            block_types = [type(b).__name__ for b in response.content]
            _log("BACKEND", (
                f"response stop_reason={response.stop_reason} "
                f"input_tokens={response.usage.input_tokens} "
                f"output_tokens={response.usage.output_tokens} "
                f"blocks={block_types}"
            ))
            return "\n".join(b.text for b in response.content if hasattr(b, "text"))

        _log("BACKEND", f"call model={model} max_tokens={max_tokens} mcp=False timeout={_TIMEOUT_PLAIN}s")
        response = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            timeout=_TIMEOUT_PLAIN,
        )
        _log("BACKEND", (
            f"response stop_reason={response.stop_reason} "
            f"input_tokens={response.usage.input_tokens} "
            f"output_tokens={response.usage.output_tokens}"
        ))
        return response.content[0].text


register_backend("anthropic", AnthropicBackend)
