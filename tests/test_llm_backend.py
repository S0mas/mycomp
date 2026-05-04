"""Tests for the LLM backend abstraction."""
import pytest

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
