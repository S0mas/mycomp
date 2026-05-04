"""
MCP server exposing project file and shell tools to Claude agents.

Run via:
    .venv/bin/python -m aicompany.mcp_server          # stdio (local testing)
    .venv/bin/python -m aicompany.mcp_server --sse    # HTTP/SSE on port 8000
    .venv/bin/python -m aicompany.mcp_server --sse --port 9000

For remote access (Anthropic API requires public URL):
    ./cloudflared tunnel --url http://localhost:8000
Then set: AICOMPANY_MCP_SERVERS='[{"type":"url","url":"https://<tunnel>.trycloudflare.com/mcp","name":"mycomp"}]'
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from aicompany import config

_BASE = config.BASE_DIR

# Parse --port before constructing FastMCP (port is a constructor param)
_port = 8000
for _i, _arg in enumerate(sys.argv):
    if _arg == "--port" and _i + 1 < len(sys.argv):
        _port = int(sys.argv[_i + 1])

_sse_mode = "--sse" in sys.argv
mcp = FastMCP(
    "mycomp",
    host="127.0.0.1",
    port=_port,
    # Disable DNS rebinding protection so cloudflare tunnel host headers pass through
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
) if _sse_mode else FastMCP("mycomp")


def _safe_path(path: str) -> Path:
    """Resolve path relative to BASE_DIR; block traversal outside it."""
    p = (_BASE / path).resolve()
    if not str(p).startswith(str(_BASE.resolve())):
        raise ValueError(f"Path outside project root: {path}")
    return p


@mcp.tool()
def read_file(path: str) -> str:
    """Read a file relative to the project root."""
    p = _safe_path(path)
    if not p.exists():
        return f"ERROR: file not found: {path}"
    return p.read_text(encoding="utf-8")


@mcp.tool()
def write_file(path: str, content: str) -> str:
    """Write content to a file relative to the project root. Creates parent dirs."""
    p = _safe_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"OK: wrote {len(content)} chars to {path}"


@mcp.tool()
def list_directory(path: str = ".") -> str:
    """List files and directories at the given path (relative to project root)."""
    p = _safe_path(path)
    if not p.exists():
        return f"ERROR: directory not found: {path}"
    entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name))
    lines = []
    for e in entries:
        prefix = "  " if e.is_file() else "/ "
        lines.append(f"{prefix}{e.name}")
    return "\n".join(lines) or "(empty)"


@mcp.tool()
def run_tests(pattern: str = "") -> str:
    """Run the pytest suite. Optionally filter by pattern (e.g. 'test_models')."""
    cmd = [str(_BASE / ".venv/bin/pytest"), "tests/", "-q"]
    if pattern:
        cmd += ["-k", pattern]
    result = subprocess.run(cmd, cwd=str(_BASE), capture_output=True, text=True, timeout=120)
    return (result.stdout + result.stderr).strip()


@mcp.tool()
def run_command(command: str) -> str:
    """Run a shell command inside the project root. Returns combined stdout+stderr."""
    result = subprocess.run(
        command, shell=True, cwd=str(_BASE),
        capture_output=True, text=True, timeout=60,
    )
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        output = f"[exit {result.returncode}]\n{output}"
    return output or "(no output)"


@mcp.tool()
def get_project_status() -> str:
    """Return git status and recent commits for the project."""
    status = subprocess.run(
        ["git", "status", "--short"], cwd=str(_BASE), capture_output=True, text=True
    ).stdout.strip()
    log = subprocess.run(
        ["git", "log", "--oneline", "-5"], cwd=str(_BASE), capture_output=True, text=True
    ).stdout.strip()
    return f"=== git status ===\n{status or '(clean)'}\n\n=== recent commits ===\n{log}"


if __name__ == "__main__":
    # streamable-http uses a single POST /mcp endpoint — compatible with Anthropic's MCP connector.
    # sse uses GET /sse + POST /messages (older split-endpoint protocol).
    transport = "streamable-http" if _sse_mode else "stdio"
    mcp.run(transport=transport)
