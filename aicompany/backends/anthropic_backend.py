"""Anthropic (Claude) LLM backend with local tool execution.

Tools (read_file, write_file, list_directory, run_tests, run_command,
get_project_status) are executed locally in-process. No MCP server or
cloudflare tunnel required.

AICOMPANY_MCP_SERVERS is still read for opt-in server-side MCP when a
remote setup is explicitly configured; otherwise the local tool loop runs.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import anthropic

from aicompany import config
from aicompany.llm_backend import register_backend

_TIMEOUT_PLAIN = int(os.environ.get("AICOMPANY_API_TIMEOUT", "120"))
_TIMEOUT_MCP   = int(os.environ.get("AICOMPANY_API_TIMEOUT_MCP", "300"))
_MAX_TOOL_ITERATIONS = 50

# ── Tool definitions (Anthropic JSON-schema format) ───────────────────────────

_TOOLS = [
    {
        "name": "read_file",
        "description": "Read a file relative to the project root.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Relative path from project root"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file relative to the project root. Creates parent dirs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path":    {"type": "string", "description": "Relative path from project root"},
                "content": {"type": "string", "description": "File content to write"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_directory",
        "description": "List files and directories at a path relative to the project root.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Relative path (default '.')"}},
            "required": [],
        },
    },
    {
        "name": "run_tests",
        "description": "Run the pytest suite. Optionally filter by pattern (e.g. 'test_models').",
        "input_schema": {
            "type": "object",
            "properties": {"pattern": {"type": "string", "description": "Optional pytest -k filter"}},
            "required": [],
        },
    },
    {
        "name": "run_command",
        "description": "Run a shell command inside the project root. Returns combined stdout+stderr.",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string", "description": "Shell command to execute"}},
            "required": ["command"],
        },
    },
    {
        "name": "get_project_status",
        "description": "Return git status and recent commits for the project.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]


# ── Local tool execution ──────────────────────────────────────────────────────

def _safe_path(rel: str) -> Path:
    base = config.BASE_DIR.resolve()
    p = (config.BASE_DIR / rel).resolve()
    if not str(p).startswith(str(base)):
        raise ValueError(f"Path outside project root: {rel}")
    return p


def _execute_tool(name: str, inputs: dict) -> str:
    try:
        if name == "read_file":
            p = _safe_path(inputs["path"])
            return p.read_text(encoding="utf-8") if p.exists() else f"ERROR: not found: {inputs['path']}"

        if name == "write_file":
            p = _safe_path(inputs["path"])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(inputs["content"], encoding="utf-8")
            return f"OK: wrote {len(inputs['content'])} chars to {inputs['path']}"

        if name == "list_directory":
            p = _safe_path(inputs.get("path", "."))
            if not p.exists():
                return f"ERROR: not found: {inputs.get('path', '.')}"
            entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name))
            return "\n".join(("  " if e.is_file() else "/ ") + e.name for e in entries) or "(empty)"

        if name == "run_tests":
            pattern = inputs.get("pattern", "")
            cmd = [str(config.BASE_DIR / ".venv/bin/pytest"), "tests/", "-q"]
            if pattern:
                cmd += ["-k", pattern]
            r = subprocess.run(cmd, cwd=str(config.BASE_DIR),
                               capture_output=True, text=True, timeout=120)
            return (r.stdout + r.stderr).strip()

        if name == "run_command":
            r = subprocess.run(inputs["command"], shell=True, cwd=str(config.BASE_DIR),
                               capture_output=True, text=True, timeout=60)
            out = (r.stdout + r.stderr).strip()
            return f"[exit {r.returncode}]\n{out}" if r.returncode != 0 else (out or "(no output)")

        if name == "get_project_status":
            status = subprocess.run(["git", "status", "--short"], cwd=str(config.BASE_DIR),
                                    capture_output=True, text=True).stdout.strip()
            log = subprocess.run(["git", "log", "--oneline", "-5"], cwd=str(config.BASE_DIR),
                                 capture_output=True, text=True).stdout.strip()
            return f"=== git status ===\n{status or '(clean)'}\n\n=== recent commits ===\n{log}"

        return f"ERROR: unknown tool: {name}"
    except Exception as exc:
        return f"ERROR: {exc}"


# ── Backend ───────────────────────────────────────────────────────────────────

class AnthropicBackend:
    """LLM backend using the Anthropic Messages API.

    By default runs a local tool-use loop — no MCP server or tunnel needed.
    If AICOMPANY_MCP_SERVERS is explicitly set, falls back to the remote
    server-side MCP beta for that session.
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

        # ── Remote server-side MCP (opt-in via AICOMPANY_MCP_SERVERS) ──────
        if self._mcp_servers:
            _log("BACKEND", f"call model={model} max_tokens={max_tokens} mcp=remote timeout={_TIMEOUT_MCP}s")
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

        # ── Local tool-use loop (default) ────────────────────────────────────
        _log("BACKEND", f"call model={model} max_tokens={max_tokens} mcp=local timeout={_TIMEOUT_PLAIN}s")
        messages: list[dict] = [{"role": "user", "content": user}]

        for iteration in range(_MAX_TOOL_ITERATIONS):
            response = self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                tools=_TOOLS,
                timeout=_TIMEOUT_PLAIN,
            )
            _log("BACKEND", (
                f"iteration={iteration} stop_reason={response.stop_reason} "
                f"input_tokens={response.usage.input_tokens} "
                f"output_tokens={response.usage.output_tokens}"
            ))

            if response.stop_reason == "end_turn":
                return "\n".join(b.text for b in response.content if hasattr(b, "text"))

            if response.stop_reason != "tool_use":
                return "\n".join(b.text for b in response.content if hasattr(b, "text"))

            # Execute each tool call locally
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    _log("TOOL", f"{block.name}({block.input})")
                    result = _execute_tool(block.name, block.input)
                    _log("TOOL", f"{block.name} → {result[:120]}{'...' if len(result) > 120 else ''}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
            messages.append({"role": "user", "content": tool_results})

        return f"ERROR: exceeded {_MAX_TOOL_ITERATIONS} tool iterations"


register_backend("anthropic", AnthropicBackend)
