"""
Reasoner implementations.

A Reasoner is the 'brain' behind a Person. It receives Messages,
composes a prompt from the Person's structured context, calls an
LLM (or other backend), and returns the response text.
"""
from __future__ import annotations

from . import config
from .llm_backend import LLMBackend, Reasoner, create_backend
from .models import Message, Person, build_prompt


class LLMReasoner:
    """Reasoner backed by any LLMBackend. Composes prompts from Person context."""

    def __init__(self, backend: LLMBackend | None = None) -> None:
        if backend is None:
            from . import backends  # noqa: F401 — trigger auto-registration
            backend = create_backend(config.LLM_BACKEND)
        self._backend = backend

    def think(
        self,
        person: Person,
        messages: list[Message],
        skill_registry: dict | None = None,
        session_rules_text: str = "",
        max_tokens: int = 4096,
    ) -> str:
        system = self._build_system(person, skill_registry, session_rules_text)
        user = self._build_user(person, messages)
        return self._backend.call(system, user, max_tokens, config.MODEL)

    def _build_system(
        self,
        person: Person,
        skill_registry: dict | None,
        session_rules_text: str,
    ) -> str:
        """Compose the system prompt from Person context + session rules."""
        base = build_prompt(person, skill_registry)
        if session_rules_text:
            base += f"\n\n{session_rules_text}"
        return base

    def _build_user(self, person: Person, messages: list[Message]) -> str:
        """Convert a list of Messages into a user prompt."""
        if not messages:
            return ""

        parts = []
        for msg in messages:
            if msg.sender == "system":
                parts.append(f"[SYSTEM] {msg.content}")
            elif msg.sender == person.id:
                parts.append(f"[YOU] {msg.content}")
            else:
                label = msg.sender
                if msg.kind != "task":
                    label = f"{msg.sender} ({msg.kind})"
                parts.append(f"[{label}] {msg.content}")

        return "\n\n---\n\n".join(parts)


# Verify LLMReasoner conforms to the protocol
assert isinstance(LLMReasoner.__new__(LLMReasoner), Reasoner)
