"""Claude CLI backend.

Delegates every agent call to the `claude` CLI (Claude Code).
Claude Code handles tool use, context compaction, prompt caching,
and rate limits internally — we just get back the final response text.
"""
from __future__ import annotations

import json
import shutil
import subprocess

from aicompany import config
from aicompany.llm_backend import register_backend


class ClaudeCLIBackend:

    def __init__(self) -> None:
        if not shutil.which("claude"):
            raise RuntimeError(
                "claude CLI not found in PATH. "
                "Install Claude Code: https://claude.ai/code"
            )

    def call(self, system: str, user: str, max_tokens: int, model: str) -> str:
        log = config.task_log.get()

        cmd = [
            "claude",
            "-p", user,
            "--output-format", "json",
            "--model", model,
            "--system-prompt", system,
            "--max-turns", "50",
        ]

        if log:
            log("BACKEND", f"claude CLI model={model}")

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(config.BASE_DIR),
            timeout=1800,
        )

        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            raise RuntimeError(
                f"claude CLI exited {proc.returncode}"
                + (f": {stderr[:400]}" if stderr else "")
            )

        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"claude CLI returned invalid JSON: {proc.stdout[:300]}"
            ) from exc

        if data.get("is_error"):
            raise RuntimeError(f"claude CLI error: {data.get('result', '')[:400]}")

        if log:
            cost = data.get("cost_usd")
            duration_ms = data.get("duration_ms")
            extras = ""
            if cost is not None:
                extras += f" cost=${cost:.4f}"
            if duration_ms is not None:
                extras += f" duration={duration_ms // 1000}s"
            log("BACKEND", f"claude CLI done{extras}")

        return data.get("result", "")


register_backend("claude_cli", ClaudeCLIBackend)
