"""Tests for AnthropicBackend — local tool loop and remote MCP paths."""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import pytest

from aicompany import config
from aicompany.backends.anthropic_backend import AnthropicBackend, _execute_tool


# ── _execute_tool (local execution) ───────────────────────────────────────────

class TestExecuteTool:
    def test_read_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "BASE_DIR", tmp_path)
        (tmp_path / "hello.txt").write_text("world")
        assert _execute_tool("read_file", {"path": "hello.txt"}) == "world"

    def test_read_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "BASE_DIR", tmp_path)
        result = _execute_tool("read_file", {"path": "nope.txt"})
        assert "not found" in result

    def test_write_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "BASE_DIR", tmp_path)
        result = _execute_tool("write_file", {"path": "sub/out.txt", "content": "hi"})
        assert "OK" in result
        assert (tmp_path / "sub" / "out.txt").read_text() == "hi"

    def test_write_file_path_traversal_blocked(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "BASE_DIR", tmp_path)
        result = _execute_tool("write_file", {"path": "../../etc/passwd", "content": "x"})
        assert "ERROR" in result

    def test_list_directory(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "BASE_DIR", tmp_path)
        (tmp_path / "a.py").write_text("")
        (tmp_path / "subdir").mkdir()
        result = _execute_tool("list_directory", {"path": "."})
        assert "a.py" in result
        assert "subdir" in result

    def test_unknown_tool_returns_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "BASE_DIR", tmp_path)
        result = _execute_tool("nonexistent_tool", {})
        assert "ERROR" in result


# ── AnthropicBackend init ──────────────────────────────────────────────────────

class TestInit:
    def test_raises_when_api_key_missing(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with patch("anthropic.Anthropic"):
            with pytest.raises(EnvironmentError, match="ANTHROPIC_API_KEY"):
                AnthropicBackend()

    def test_default_reads_config_mcp_servers(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        server = {"type": "url", "url": "https://x.com/mcp", "name": "s"}
        monkeypatch.setattr(config, "MCP_SERVERS", [server])
        with patch("anthropic.Anthropic"):
            backend = AnthropicBackend()
        assert backend._mcp_servers == [server]


# ── Local tool-use loop (default path) ────────────────────────────────────────

class TestLocalToolLoop:
    def _make_backend(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setattr(config, "MCP_SERVERS", [])
        mock_client = MagicMock()
        with patch("anthropic.Anthropic", return_value=mock_client):
            backend = AnthropicBackend(mcp_servers=[])
        return backend, mock_client

    def test_end_turn_returns_text(self, monkeypatch):
        backend, mock_client = self._make_backend(monkeypatch)
        text_block = MagicMock(type="text", text="final answer")
        mock_client.messages.create.return_value = MagicMock(
            stop_reason="end_turn",
            content=[text_block],
            usage=MagicMock(input_tokens=10, output_tokens=5),
        )
        result = backend.call("sys", "user", 1024, "claude-test")
        assert result == "final answer"
        assert mock_client.messages.create.call_count == 1

    def test_tool_use_loop_executes_locally(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config, "BASE_DIR", tmp_path)
        (tmp_path / "info.txt").write_text("hello from file")

        backend, mock_client = self._make_backend(monkeypatch)

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.id = "tu_1"
        tool_block.name = "read_file"
        tool_block.input = {"path": "info.txt"}
        final_block = MagicMock(type="text", text="done")
        tool_response = MagicMock(stop_reason="tool_use", content=[tool_block],
                                  usage=MagicMock(input_tokens=10, output_tokens=5))
        end_response = MagicMock(stop_reason="end_turn", content=[final_block],
                                 usage=MagicMock(input_tokens=20, output_tokens=3))

        mock_client.messages.create.side_effect = [tool_response, end_response]

        result = backend.call("sys", "user", 1024, "claude-test")

        assert result == "done"
        assert mock_client.messages.create.call_count == 2
        # Second call must include tool result
        second_call_messages = mock_client.messages.create.call_args_list[1][1]["messages"]
        tool_result_msg = second_call_messages[-1]
        assert tool_result_msg["role"] == "user"
        assert any(
            r.get("type") == "tool_result" and "hello from file" in r.get("content", "")
            for r in tool_result_msg["content"]
        )

    def test_max_iterations_guard(self, monkeypatch):
        backend, mock_client = self._make_backend(monkeypatch)
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.id = "tu_x"
        tool_block.name = "get_project_status"
        tool_block.input = {}
        infinite_response = MagicMock(stop_reason="tool_use", content=[tool_block],
                                      usage=MagicMock(input_tokens=5, output_tokens=5))
        mock_client.messages.create.return_value = infinite_response

        with patch("aicompany.backends.anthropic_backend._execute_tool", return_value="ok"), \
             patch("aicompany.backends.anthropic_backend._MAX_TOOL_ITERATIONS", 3):
            result = backend.call("sys", "user", 512, "m")

        assert "exceeded" in result
        assert mock_client.messages.create.call_count == 3

    def test_tools_included_in_request(self, monkeypatch):
        backend, mock_client = self._make_backend(monkeypatch)
        mock_client.messages.create.return_value = MagicMock(
            stop_reason="end_turn",
            content=[MagicMock(type="text", text="ok")],
            usage=MagicMock(input_tokens=5, output_tokens=2),
        )
        backend.call("sys", "user", 512, "m")
        kwargs = mock_client.messages.create.call_args[1]
        assert "tools" in kwargs
        tool_names = [t["name"] for t in kwargs["tools"]]
        assert "read_file" in tool_names
        assert "write_file" in tool_names


# ── Remote MCP path (opt-in via AICOMPANY_MCP_SERVERS) ────────────────────────

class TestRemoteMCPPath:
    def _make_backend(self, monkeypatch, mcp_servers):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setattr(config, "MCP_SERVERS", [])
        mock_client = MagicMock()
        with patch("anthropic.Anthropic", return_value=mock_client):
            backend = AnthropicBackend(mcp_servers=mcp_servers)
        return backend, mock_client

    def test_uses_beta_when_mcp_servers_set(self, monkeypatch):
        servers = [{"type": "url", "url": "https://x.com/mcp", "name": "s"}]
        backend, mock_client = self._make_backend(monkeypatch, servers)
        text_block = MagicMock(text="mcp response")
        mock_client.beta.messages.create.return_value = MagicMock(
            content=[text_block],
            stop_reason="end_turn",
            usage=MagicMock(input_tokens=10, output_tokens=5),
        )
        result = backend.call("sys", "user", 2048, "claude-test")
        assert result == "mcp response"
        mock_client.beta.messages.create.assert_called_once()
        mock_client.messages.create.assert_not_called()

    def test_local_loop_when_no_mcp_servers(self, monkeypatch):
        backend, mock_client = self._make_backend(monkeypatch, [])
        mock_client.messages.create.return_value = MagicMock(
            stop_reason="end_turn",
            content=[MagicMock(type="text", text="local")],
            usage=MagicMock(input_tokens=5, output_tokens=2),
        )
        result = backend.call("sys", "user", 512, "m")
        assert result == "local"
        mock_client.messages.create.assert_called_once()
        mock_client.beta.messages.create.assert_not_called()
