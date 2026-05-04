"""
Chat-session LLM backend.

Enables an AI assistant in an interactive chat session (e.g. Claude in VS Code,
Copilot, Cursor) to act as the LLM backend for mycomp. The app writes a request
to a file, the AI reads it and writes a response file.

Flow:
  1. App writes /tmp/mycomp_llm/request.json  (system + user prompt)
  2. App polls for  /tmp/mycomp_llm/response.txt
  3. Chat AI reads the request, thinks, writes the response
  4. App reads response.txt, deletes both files, returns the text

Configure via:
  AICOMPANY_LLM_BACKEND=chat_session
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from aicompany.llm_backend import register_backend
from aicompany import config

_EXCHANGE_DIR = Path(os.environ.get("MYCOMP_EXCHANGE_DIR", str(config.BASE_DIR / "tmp" / "llm_exchange")))
_POLL_INTERVAL = 1.0  # seconds between checks
_TIMEOUT = 600  # 10 minutes max wait


class ChatSessionBackend:
    """LLM backend that communicates via filesystem with a chat AI session."""

    def __init__(self) -> None:
        self._exchange_dir = _EXCHANGE_DIR
        self._exchange_dir.mkdir(parents=True, exist_ok=True)
        # Clean up any stale files
        for f in ("request.json", "response.txt"):
            (self._exchange_dir / f).unlink(missing_ok=True)

    def call(self, system: str, user: str, max_tokens: int, model: str) -> str:
        request_file = self._exchange_dir / "request.json"
        response_file = self._exchange_dir / "response.txt"

        # Clean previous response
        response_file.unlink(missing_ok=True)

        # Write request
        request_data = {
            "system": system,
            "user": user,
            "max_tokens": max_tokens,
            "model": model,
        }
        request_file.write_text(json.dumps(request_data, indent=2), encoding="utf-8")

        # Signal file — tells the AI a request is waiting
        signal = self._exchange_dir / "WAITING"
        signal.write_text("Request ready. Waiting for response.", encoding="utf-8")

        # Poll for response
        elapsed = 0.0
        while elapsed < _TIMEOUT:
            if response_file.exists():
                text = response_file.read_text(encoding="utf-8").strip()
                if text:
                    # Clean up
                    request_file.unlink(missing_ok=True)
                    response_file.unlink(missing_ok=True)
                    signal.unlink(missing_ok=True)
                    return text
            time.sleep(_POLL_INTERVAL)
            elapsed += _POLL_INTERVAL

        # Timeout
        signal.unlink(missing_ok=True)
        request_file.unlink(missing_ok=True)
        raise TimeoutError(
            f"No response received within {_TIMEOUT}s. "
            f"Ensure the chat AI is monitoring {self._exchange_dir}"
        )


register_backend("chat_session", ChatSessionBackend)
