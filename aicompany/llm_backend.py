"""
LLM backend abstraction.

Defines the protocol that any LLM provider must implement,
plus a registry for selecting backends by name.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMBackend(Protocol):
    """Any LLM provider must implement this interface."""

    def call(self, system: str, user: str, max_tokens: int, model: str) -> str:
        """Send a single system+user message pair and return the response text."""
        ...


# ── Backend registry ───────────────────────────────────────────────────────────

_REGISTRY: dict[str, type[LLMBackend]] = {}


def register_backend(name: str, cls: type[LLMBackend]) -> None:
    """Register a backend class under a name (e.g. 'anthropic', 'openai')."""
    _REGISTRY[name] = cls


def create_backend(name: str) -> LLMBackend:
    """Instantiate a backend by name. Raises KeyError if unknown."""
    if name not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise KeyError(
            f"Unknown LLM backend: '{name}'. Available: {available}. "
            f"Set AICOMPANY_LLM_BACKEND to one of these."
        )
    return _REGISTRY[name]()
