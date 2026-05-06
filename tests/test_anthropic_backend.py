"""Tests for AnthropicBackend — plain and MCP paths. All LLM calls mocked."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from aicompany import config
from aicompany.backends.anthropic_backend import AnthropicBackend


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


class TestPlainCall:
    def test_uses_messages_create(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setattr(config, "MCP_SERVERS", [])

        mock_client = MagicMock()
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="plain response")]
        )

        with patch("anthropic.Anthropic", return_value=mock_client):
            backend = AnthropicBackend(mcp_servers=[])

        result = backend.call("sys", "user msg", 1024, "claude-test")

        mock_client.messages.create.assert_called_once_with(
            model="claude-test",
            max_tokens=1024,
            system="sys",
            messages=[{"role": "user", "content": "user msg"}],
            timeout=mock_client.messages.create.call_args.kwargs["timeout"],
        )
        mock_client.beta.messages.create.assert_not_called()
        assert result == "plain response"


class TestMCPCall:
    def _make_backend(self, monkeypatch, mcp_servers):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setattr(config, "MCP_SERVERS", [])
        mock_client = MagicMock()
        with patch("anthropic.Anthropic", return_value=mock_client):
            backend = AnthropicBackend(mcp_servers=mcp_servers)
        return backend, mock_client

    def test_uses_beta_messages_create(self, monkeypatch):
        servers = [{"type": "url", "url": "https://x.com/mcp", "name": "s"}]
        backend, mock_client = self._make_backend(monkeypatch, servers)

        text_block = MagicMock()
        text_block.text = "mcp response"
        tool_block = MagicMock(spec=[])  # no 'text' attr
        mock_client.beta.messages.create.return_value = MagicMock(
            content=[tool_block, text_block]
        )

        result = backend.call("sys", "user msg", 2048, "claude-test")

        mock_client.beta.messages.create.assert_called_once_with(
            model="claude-test",
            max_tokens=2048,
            system="sys",
            messages=[{"role": "user", "content": "user msg"}],
            mcp_servers=servers,
            betas=["mcp-client-2025-04-04"],
            timeout=mock_client.beta.messages.create.call_args.kwargs["timeout"],
        )
        mock_client.messages.create.assert_not_called()
        assert result == "mcp response"

    def test_multiple_text_blocks_joined(self, monkeypatch):
        servers = [{"type": "url", "url": "https://x.com/mcp", "name": "s"}]
        backend, mock_client = self._make_backend(monkeypatch, servers)

        block_a = MagicMock()
        block_a.text = "part one"
        block_b = MagicMock()
        block_b.text = "part two"
        mock_client.beta.messages.create.return_value = MagicMock(
            content=[block_a, block_b]
        )

        result = backend.call("s", "u", 512, "m")
        assert result == "part one\npart two"

    def test_empty_mcp_servers_takes_plain_path(self, monkeypatch):
        backend, mock_client = self._make_backend(monkeypatch, [])
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="ok")]
        )
        backend.call("s", "u", 256, "m")
        mock_client.messages.create.assert_called_once()
        mock_client.beta.messages.create.assert_not_called()
