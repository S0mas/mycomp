"""
LLM backend and Reasoner abstractions.

LLMBackend — transport layer: send prompt, get text back.
Reasoner   — agent layer: given a Person and Messages, produce a response.

These are separate concerns:
  - LLMBackend knows nothing about persons or messages
  - Reasoner knows nothing about APIs or HTTP
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .models import Message, Person


@runtime_checkable
class LLMBackend(Protocol):
    """Any LLM provider must implement this interface."""

    def call(self, system: str, user: str, max_tokens: int, model: str) -> str:
        """Send a single system+user message pair and return the response text."""
        ...


@runtime_checkable
class Reasoner(Protocol):
    """Turns a Person + messages into a response. The 'brain' behind a Person."""

    def setup(
        self,
        persons: list[Person],
        skill_registry: dict | None = None,
    ) -> None:
        """
        Prepare the reasoner for a session with the given persons.
        Called once before think() calls begin. Default is a no-op.
        """
        ...

    def think(
        self,
        person: Person,
        messages: list[Message],
        skill_registry: dict | None = None,
        session_rules_text: str = "",
        max_tokens: int = 4096,
    ) -> str:
        """
        Given who the person is and what messages they've received,
        produce a response.

        Args:
            person: The Person doing the thinking
            messages: Messages this person has received/sent in this session
            skill_registry: {skill_id: Skill} for prompt composition
            session_rules_text: Human-readable session rules (person is aware of these)
            max_tokens: Response budget
        """
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
