"""Tests for the LLM backend abstraction."""
import pytest
from unittest.mock import MagicMock, patch

from aicompany.llm_backend import LLMBackend, register_backend, create_backend, _REGISTRY


class DummyBackend:
    """A test backend that echoes the user message."""
    def call(self, system: str, user: str, max_tokens: int, model: str) -> str:
        return f"echo: {user}"


class TestLLMBackend:
    def setup_method(self):
        self._original = dict(_REGISTRY)

    def teardown_method(self):
        _REGISTRY.clear()
        _REGISTRY.update(self._original)

    def test_register_and_create(self):
        register_backend("dummy", DummyBackend)
        backend = create_backend("dummy")
        assert isinstance(backend, DummyBackend)
        assert backend.call("sys", "hello", 100, "m") == "echo: hello"

    def test_unknown_backend_raises(self):
        with pytest.raises(KeyError, match="Unknown LLM backend"):
            create_backend("nonexistent_provider")

    def test_protocol_check(self):
        assert isinstance(DummyBackend(), LLMBackend)

    def test_non_conforming_class_fails_protocol(self):
        class Bad:
            pass
        assert not isinstance(Bad(), LLMBackend)


class TestLLMReasoner:
    def test_think_retries_on_transient_error(self):
        from aicompany.reasoner import LLMReasoner
        from aicompany.models import Person, Message

        backend = MagicMock()
        backend.call.side_effect = [RuntimeError("timeout"), RuntimeError("timeout"), "final answer"]

        reasoner = LLMReasoner(backend=backend)
        person = Person(id="p", name="P", role="coder", identity="You are a coder.")
        messages = [Message(sender="system", recipient="p", kind="task", content="Do it")]

        with patch("aicompany.reasoner.time.sleep"):
            result = reasoner.think(person, messages)

        assert result == "final answer"
        assert backend.call.call_count == 3

    def test_think_raises_after_three_failures(self):
        from aicompany.reasoner import LLMReasoner
        from aicompany.models import Person, Message

        backend = MagicMock()
        backend.call.side_effect = RuntimeError("always fails")

        reasoner = LLMReasoner(backend=backend)
        person = Person(id="p", name="P", role="coder", identity="You are a coder.")
        messages = []

        with patch("aicompany.reasoner.time.sleep"):
            with pytest.raises(RuntimeError, match="always fails"):
                reasoner.think(person, messages)

        assert backend.call.call_count == 3


class TestLLMCall:
    def test_call_retries_on_transient_error(self):
        from aicompany.llm import _call

        backend = MagicMock()
        backend.call.side_effect = [ConnectionError("net"), ConnectionError("net"), "ok"]

        with patch("aicompany.llm.time.sleep"):
            result = _call("sys", "user", 100, backend=backend)

        assert result == "ok"
        assert backend.call.call_count == 3

    def test_call_raises_after_three_failures(self):
        from aicompany.llm import _call

        backend = MagicMock()
        backend.call.side_effect = ConnectionError("always")

        with patch("aicompany.llm.time.sleep"):
            with pytest.raises(ConnectionError, match="always"):
                _call("sys", "user", 100, backend=backend)

        assert backend.call.call_count == 3
