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

import time

import httpx

from . import config
from .llm_backend import LLMBackend, LLMRateLimitError, Reasoner, create_backend
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
        log = config.task_log.get()
        rate_limit_count = 0
        attempt = 0
        while attempt < config.LLM_RETRY_ATTEMPTS:
            try:
                return self._backend.call(system, user, max_tokens, config.MODEL)
            except LLMRateLimitError:
                rate_limit_count += 1
                if rate_limit_count > config.LLM_RATE_LIMIT_MAX_RETRIES:
                    raise
                wait = config.LLM_RATE_LIMIT_WAIT
                if log:
                    log("RATE_LIMIT", f"Rate limited ({rate_limit_count}/{config.LLM_RATE_LIMIT_MAX_RETRIES})"
                                      f" — waiting {wait}s before retry")
                time.sleep(wait)
                # Rate limit retries don't consume attempt budget
            except Exception as exc:
                attempt += 1
                if attempt >= config.LLM_RETRY_ATTEMPTS:
                    raise
                if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
                    raise
                if "Connection error while communicating with MCP server" in str(exc):
                    if log:
                        log("ERROR", "MCP server unreachable — tunnel may have dropped.")
                    raise
                wait = config.LLM_RETRY_BACKOFF_BASE ** (attempt - 1)
                if log:
                    log("RETRY", f"attempt {attempt}/{config.LLM_RETRY_ATTEMPTS} failed: "
                                 f"{type(exc).__name__}: {exc} — retrying in {wait:.0f}s")
                time.sleep(wait)


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
