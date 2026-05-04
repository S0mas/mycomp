"""
OpenAI-compatible LLM backend.

Works with any provider exposing the OpenAI chat completions API:
  - OpenAI itself
  - Ollama (http://localhost:11434/v1)
  - LM Studio (http://localhost:1234/v1)
  - vLLM, LiteLLM, LocalAI, etc.
  - Claude via openai-compatible proxies

Configure via environment variables:
  AICOMPANY_LLM_BACKEND=openai
  AICOMPANY_MODEL=gpt-4o  (or any model the provider supports)
  OPENAI_API_KEY=...       (or "none" for local providers)
  OPENAI_BASE_URL=...      (optional, defaults to https://api.openai.com/v1)
"""
from __future__ import annotations

import json
import os
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from aicompany.llm_backend import register_backend


class OpenAIBackend:
    """LLM backend using the OpenAI-compatible chat completions API (no SDK dependency)."""

    def __init__(self) -> None:
        self._api_key = os.environ.get("OPENAI_API_KEY", "")
        if not self._api_key:
            raise EnvironmentError(
                "OPENAI_API_KEY is not set. "
                "Export it or set it to 'none' for local providers (Ollama, LM Studio)."
            )
        self._base_url = os.environ.get(
            "OPENAI_BASE_URL", "https://api.openai.com/v1"
        ).rstrip("/")

    def call(self, system: str, user: str, max_tokens: int, model: str) -> str:
        url = f"{self._base_url}/chat/completions"
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        req = Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
        try:
            with urlopen(req) as resp:
                data = json.loads(resp.read().decode())
        except HTTPError as e:
            body = e.read().decode() if e.fp else ""
            raise RuntimeError(
                f"OpenAI-compatible API error {e.code}: {body}"
            ) from e
        return data["choices"][0]["message"]["content"]


register_backend("openai", OpenAIBackend)
