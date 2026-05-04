"""
Reasoner implementations.

A Reasoner is the 'brain' behind a Person. It receives Messages,
composes a prompt from the Person's structured context, calls an
LLM (or other backend), and returns the response text.

Two implementations:
  - LLMReasoner: wraps any LLMBackend (API-based, fake, etc.)
  - ChatSessionReasoner: per-person file exchange for interactive chat sessions
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

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


# ── ChatSessionReasoner ──────────────────────────────────────────────────────

_POLL_INTERVAL = 1.0
_TIMEOUT = int(os.environ.get("MYCOMP_CHAT_TIMEOUT", "600"))


class ChatSessionReasoner:
    """
    Reasoner for interactive chat sessions (e.g. multiple Claude tabs).

    Each Person gets their own exchange directory under ``exchange_root/{person_id}/``.
    Before the session starts, call ``print_instructions()`` to tell the user
    which tabs to open and what to paste into each.

    File protocol per person dir:
        persona.md     — written once; describes who this agent is
        request.json   — written by orchestrator when it needs a response
        WAITING        — signal that a request is pending
        response.txt   — written by the chat AI; orchestrator reads and deletes
    """

    def __init__(self, exchange_root: Path | None = None) -> None:
        self._root = exchange_root or Path(
            os.environ.get(
                "MYCOMP_EXCHANGE_DIR",
                str(config.BASE_DIR / "tmp" / "llm_exchange"),
            )
        )
        self._root.mkdir(parents=True, exist_ok=True)
        self._prepared_persons: dict[str, Person] = {}

    # ── Setup ─────────────────────────────────────────────────────────────

    def prepare_person(
        self,
        person: Person,
        skill_registry: dict | None = None,
    ) -> Path:
        """Create exchange dir and write persona card for a person."""
        pdir = self._root / person.id
        pdir.mkdir(parents=True, exist_ok=True)
        # Clean stale files
        for f in ("request.json", "response.txt", "WAITING"):
            (pdir / f).unlink(missing_ok=True)
        # Write persona card
        persona_card = self._build_persona_card(person, skill_registry)
        (pdir / "persona.md").write_text(persona_card, encoding="utf-8")
        self._prepared_persons[person.id] = person
        return pdir

    def prepare_all(
        self,
        persons: list[Person],
        skill_registry: dict | None = None,
    ) -> None:
        """Prepare exchange dirs for all persons in a team."""
        for p in persons:
            self.prepare_person(p, skill_registry)

    def print_instructions(self) -> str:
        """
        Return (and print) user-facing instructions: how many tabs to open
        and the exact message to paste into each.
        """
        if not self._prepared_persons:
            return ""

        lines = [
            "",
            "=" * 70,
            "  CHAT SESSION SETUP",
            "=" * 70,
            "",
            f"  Open {len(self._prepared_persons)} separate AI chat tab(s).",
            f"  Exchange directory: {self._root}",
            "",
        ]

        for i, (pid, person) in enumerate(self._prepared_persons.items(), 1):
            pdir = self._root / pid
            persona_path = pdir / "persona.md"
            init_message = self._build_init_message(person, pdir)

            lines.append(f"  ── Tab {i}: {person.name} ({person.role}) ──")
            lines.append(f"  Persona card: {persona_path}")
            lines.append(f"  Exchange dir: {pdir}")
            lines.append("")
            lines.append("  Paste the following message into the tab:")
            lines.append("  " + "─" * 50)
            for ml in init_message.splitlines():
                lines.append(f"  {ml}")
            lines.append("  " + "─" * 50)
            lines.append("")

        lines.append("=" * 70)
        lines.append("")

        text = "\n".join(lines)
        print(text)
        return text

    # ── Reasoner.think() ──────────────────────────────────────────────────

    def think(
        self,
        person: Person,
        messages: list[Message],
        skill_registry: dict | None = None,
        session_rules_text: str = "",
        max_tokens: int = 4096,
    ) -> str:
        """Write request to person's exchange dir and wait for response."""
        pdir = self._root / person.id
        pdir.mkdir(parents=True, exist_ok=True)

        system = self._build_system(person, skill_registry, session_rules_text)
        user = self._build_user(person, messages)

        request_file = pdir / "request.json"
        response_file = pdir / "response.txt"
        signal = pdir / "WAITING"

        # Clean previous
        response_file.unlink(missing_ok=True)

        request_data = {
            "system": system,
            "user": user,
            "max_tokens": max_tokens,
            "person_id": person.id,
            "person_name": person.name,
        }
        request_file.write_text(json.dumps(request_data, indent=2), encoding="utf-8")
        signal.write_text(
            f"Request ready for {person.name} ({person.id}). "
            "Read request.json, write your response to response.txt.",
            encoding="utf-8",
        )

        print(f"    ⏳ Waiting for response from {person.name} ({person.id})...")
        print(f"       Exchange dir: {pdir}")

        elapsed = 0.0
        while elapsed < _TIMEOUT:
            if response_file.exists():
                text = response_file.read_text(encoding="utf-8").strip()
                if text:
                    request_file.unlink(missing_ok=True)
                    response_file.unlink(missing_ok=True)
                    signal.unlink(missing_ok=True)
                    return text
            time.sleep(_POLL_INTERVAL)
            elapsed += _POLL_INTERVAL

        signal.unlink(missing_ok=True)
        request_file.unlink(missing_ok=True)
        raise TimeoutError(
            f"No response from {person.name} ({person.id}) within {_TIMEOUT}s. "
            f"Ensure a chat AI is monitoring {pdir}"
        )

    # ── Internal prompt building (same as LLMReasoner) ────────────────────

    def _build_system(
        self, person: Person, skill_registry: dict | None, session_rules_text: str,
    ) -> str:
        base = build_prompt(person, skill_registry)
        if session_rules_text:
            base += f"\n\n{session_rules_text}"
        return base

    def _build_user(self, person: Person, messages: list[Message]) -> str:
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

    def _build_persona_card(self, person: Person, skill_registry: dict | None) -> str:
        """Build a Markdown persona card for the chat AI tab."""
        prompt = build_prompt(person, skill_registry)
        return f"""\
# Persona: {person.name}

**ID**: `{person.id}`
**Role**: {person.role}

---

## System prompt

{prompt}

---

## How this works

You are acting as **{person.name}** in an AI company simulation.

1. A file called `request.json` will appear in this directory.
2. Read the `system` and `user` fields from it.
3. Think as {person.name} would, following the system prompt above.
4. Write **only** your response text to `response.txt` in this same directory.
5. Do NOT include any preamble like "Here is my response" — just the actual content.
6. After writing `response.txt`, wait for the next `request.json`.
"""

    def _build_init_message(self, person: Person, pdir: Path) -> str:
        """Build the message a user should paste into a new chat tab."""
        return f"""\
You are **{person.name}** (role: {person.role}, id: {person.id}).

You will act as this person in an AI company simulation. Here is how:

1. Monitor the directory: `{pdir}`
2. When a file called `WAITING` appears, read `request.json` from the same directory.
3. The `request.json` contains `system` and `user` fields — treat them as your system prompt and user message.
4. Think carefully according to the `system` prompt (your persona and rules).
5. Write ONLY your response to `{pdir}/response.txt`.
6. Do not add any wrapper text — just the raw response content.
7. After writing, wait for the next `WAITING` signal.

Your persona card is at: `{pdir}/persona.md`

Confirm you understand by saying "Ready" and then start monitoring."""


# ── Factory ───────────────────────────────────────────────────────────────────

def create_reasoner(backend_name: str | None = None) -> LLMReasoner | ChatSessionReasoner:
    """Create the appropriate Reasoner based on the configured backend."""
    name = backend_name or config.LLM_BACKEND
    if name == "chat_session":
        return ChatSessionReasoner()
    return LLMReasoner()


# Verify both conform to the protocol
assert isinstance(LLMReasoner.__new__(LLMReasoner), Reasoner)
assert isinstance(ChatSessionReasoner.__new__(ChatSessionReasoner), Reasoner)
