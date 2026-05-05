"""
Reasoner -- the abstraction layer between the orchestrator and LLM backends.

A Reasoner is the 'brain' behind a Person. It receives Messages,
composes a prompt from the Person's structured context, calls an
LLM (or other backend), and returns the response text.

This module is backend-agnostic. Implementations live with their backends:
  - LLMReasoner: here (generic, wraps any LLMBackend)
  - ChatSessionReasoner: in backends/chat_session_backend.py
"""
from __future__ import annotations

from . import config
from .llm_backend import LLMBackend, Reasoner, create_backend
from .models import Message, Person, Skill, build_prompt


def build_system_prompt(
    person: Person,
    skill_registry: dict[str, Skill] | None,
    session_rules_text: str,
) -> str:
    """Compose the system prompt from a Person's context and session rules."""
    base = build_prompt(person, skill_registry)
    if session_rules_text:
        base += f"\n\n{session_rules_text}"
    return base


def build_user_prompt(person: Person, messages: list[Message]) -> str:
    """Convert a list of Messages into a single user prompt string."""
    if not messages:
        return ""
    parts = []
    for msg in messages:
        if msg.sender == "system":
            parts.append(f"[SYSTEM] {msg.content}")
        elif msg.sender == person.id:
            parts.append(f"[YOU] {msg.content}")
        else:
            label = msg.sender if msg.kind == "task" else f"{msg.sender} ({msg.kind})"
            parts.append(f"[{label}] {msg.content}")
    return "\n\n---\n\n".join(parts)


class LLMReasoner:
    """Reasoner backed by any LLMBackend. Composes prompts from Person context."""

    def __init__(self, backend: LLMBackend | None = None) -> None:
        if backend is None:
            from . import backends  # noqa: F401
            backend = create_backend(config.LLM_BACKEND)
        self._backend = backend

    def setup(self, persons: list[Person], skill_registry: dict[str, Skill] | None = None) -> None:
        """No-op -- API-based backends don't need per-person preparation."""

    def think(
        self,
        person: Person,
        messages: list[Message],
        skill_registry: dict[str, Skill] | None = None,
        session_rules_text: str = "",
        max_tokens: int = 4096,
    ) -> str:
        system = build_system_prompt(person, skill_registry, session_rules_text)
        user = build_user_prompt(person, messages)
        return self._backend.call(system, user, max_tokens, config.MODEL)


# Verify conformance to protocol
assert isinstance(LLMReasoner.__new__(LLMReasoner), Reasoner)


# -- Factory -------------------------------------------------------------------

def create_reasoner(backend_name: str | None = None):
    """Create the appropriate Reasoner based on the configured backend."""
    name = backend_name or config.LLM_BACKEND
    if name == "chat_session":
        from .backends.chat_session_backend import ChatSessionReasoner
        return ChatSessionReasoner()
    return LLMReasoner()


# Lazy import so `from aicompany.reasoner import ChatSessionReasoner` still works
def __getattr__(name: str):
    if name == "ChatSessionReasoner":
        from .backends.chat_session_backend import ChatSessionReasoner
        return ChatSessionReasoner
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
