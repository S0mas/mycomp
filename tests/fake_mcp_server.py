"""Minimal in-process MCP server for testing. Implements the required tool interface."""
from __future__ import annotations

import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP


def create_fake_mcp(workspace: Path) -> FastMCP:
    """Create a FastMCP server scoped to workspace. Implements the 4 required tools."""
    server = FastMCP("fake-mycomp")

    def _safe(path: str) -> Path:
        p = (workspace / path).resolve()
        if not str(p).startswith(str(workspace.resolve())):
            raise ValueError(f"Path outside workspace: {path}")
        return p

    @server.tool()
    def write_file(path: str, content: str) -> str:
        """Write content to a file relative to workspace root. Creates parent dirs."""
        p = _safe(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"OK: wrote {len(content)} chars to {path}"

    @server.tool()
    def read_file(path: str) -> str:
        """Read a file relative to workspace root."""
        p = _safe(path)
        if not p.exists():
            return f"ERROR: not found: {path}"
        return p.read_text(encoding="utf-8")

    @server.tool()
    def list_directory(path: str = ".") -> str:
        """List files at path relative to workspace root."""
        p = _safe(path)
        if not p.exists():
            return f"ERROR: not found: {path}"
        return "\n".join(
            sorted(str(e.relative_to(workspace)) for e in p.iterdir())
        )

    @server.tool()
    def run_command(command: str) -> str:
        """Run a shell command inside the workspace. Returns combined stdout+stderr."""
        result = subprocess.run(
            command, shell=True, cwd=str(workspace),
            capture_output=True, text=True, timeout=30,
        )
        return (result.stdout + result.stderr).strip() or "(no output)"

    return server
