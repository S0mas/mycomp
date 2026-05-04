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

    def setup(self, persons: list[Person], skill_registry: dict | None = None) -> None:
        """No-op — API-based backends don't need per-person preparation."""

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
    The AI uses non-blocking commands to interact:
      - ``python3 worker.py poll``   — claims work, prints request, exits
      - ``python3 worker.py submit`` — reads stdin, atomically writes response

    Atomic protocol (race-free):
      1. Orchestrator writes request.json, then atomically creates READY (tmp+rename)
      2. AI runs poll → deletes READY (claims), reads request.json, prints it
      3. AI runs submit → writes .tmp, renames to response.txt (atomic)
      4. Orchestrator sees response.txt, reads it, cleans up
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

    def setup(
        self,
        persons: list[Person],
        skill_registry: dict | None = None,
    ) -> None:
        """Prepare per-person exchange dirs and print tab instructions."""
        self.prepare_all(persons, skill_registry)
        self.print_instructions()

    def prepare_person(
        self,
        person: Person,
        skill_registry: dict | None = None,
    ) -> Path:
        """Create exchange dir, write persona card and loop.py for a person."""
        pdir = self._root / person.id
        pdir.mkdir(parents=True, exist_ok=True)
        # Don't clean request/response/WAITING — think() manages those.
        # Only overwrite persona and loop script.
        # Write persona card
        persona_card = self._build_persona_card(person, skill_registry)
        (pdir / "persona.md").write_text(persona_card, encoding="utf-8")
        # Write the worker script (poll/submit)
        worker_script = self._build_worker_script(person, pdir, skill_registry)
        (pdir / "worker.py").write_text(worker_script, encoding="utf-8")
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
        and what to tell each AI.
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
            f"  Each AI uses worker.py (non-blocking poll/submit commands).",
            "",
            "  Protocol per AI tab:",
            "    1. python3 <dir>/worker.py identity   — see who you are",
            "    2. python3 <dir>/worker.py poll       — check for work (repeat until not NO_WORK)",
            "    3. python3 <dir>/worker.py submit << 'EOF'",
            "       ...response...",
            "       EOF",
            "    4. Repeat from step 2.",
            "",
        ]

        for i, (pid, person) in enumerate(self._prepared_persons.items(), 1):
            pdir = self._root / pid
            lines.append(f"  Tab {i}: {person.name} ({person.role})")
            lines.append(f"    → python3 {pdir}/worker.py poll")
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
        ready_signal = pdir / "READY"

        # Clean previous response
        response_file.unlink(missing_ok=True)
        (pdir / "response.tmp").unlink(missing_ok=True)

        # Write request data
        request_data = {
            "system": system,
            "user": user,
            "max_tokens": max_tokens,
            "person_id": person.id,
            "person_name": person.name,
        }
        request_file.write_text(json.dumps(request_data, indent=2), encoding="utf-8")

        # Atomically create READY signal (write tmp + rename)
        tmp_ready = pdir / "READY.tmp"
        tmp_ready.write_text("1", encoding="utf-8")
        tmp_ready.rename(ready_signal)

        print(f"    ⏳ Waiting for response from {person.name} ({person.id})...")
        print(f"       Exchange dir: {pdir}")

        elapsed = 0.0
        while elapsed < _TIMEOUT:
            if response_file.exists():
                text = response_file.read_text(encoding="utf-8").strip()
                if text:
                    request_file.unlink(missing_ok=True)
                    response_file.unlink(missing_ok=True)
                    ready_signal.unlink(missing_ok=True)
                    return text
            time.sleep(_POLL_INTERVAL)
            elapsed += _POLL_INTERVAL

        ready_signal.unlink(missing_ok=True)
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
# {person.name} (`{person.id}`, role: `{person.role}`)

## Identity

{prompt}

## How this works

Use `worker.py` in this directory (non-blocking, no stdin required):

1. `python3 worker.py poll` — check for work. If READY, prints the request and exits.
2. You read the request, formulate your response.
3. `python3 worker.py submit` — reads your response from stdin (heredoc), writes atomically.

Example submit:
```
python3 worker.py submit << 'EOF'
Your response here...
EOF
```
"""

    def _build_worker_script(self, person: Person, pdir: Path, skill_registry: dict | None = None) -> str:
        """Build worker.py — non-blocking poll/submit commands for AI chat tabs.

        No interactive stdin loops. AI runs discrete commands:
          python3 worker.py poll    — claim & print request (or 'NO_WORK')
          python3 worker.py submit  — read stdin, atomically write response.txt
        """
        persona_card = self._build_persona_card(person, skill_registry)
        escaped_persona = persona_card.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')

        template = '''\
#!/usr/bin/env python3
"""
Worker script for {name} ({pid}).
Generated by the orchestrator. Non-blocking — run poll/submit as separate commands.
"""
import json
import os
import sys
from pathlib import Path

EXCHANGE_DIR = Path(r"{exchange_dir}")
PERSON_NAME = "{name}"
PERSON_ID = "{pid}"
PERSON_ROLE = "{role}"

IDENTITY = """{persona}"""


def cmd_poll():
    """Check for work. If READY exists, claim it, print request, exit."""
    ready = EXCHANGE_DIR / "READY"
    request_file = EXCHANGE_DIR / "request.json"

    if not ready.exists():
        print("NO_WORK")
        return

    # Claim the work by deleting READY
    try:
        ready.unlink()
    except FileNotFoundError:
        # Another process claimed it
        print("NO_WORK")
        return

    if not request_file.exists():
        print("ERROR: READY existed but no request.json found")
        return

    data = json.loads(request_file.read_text(encoding="utf-8"))
    system_prompt = data.get("system", "")
    user_prompt = data.get("user", "")

    print("=" * 60)
    print("  WORK AVAILABLE — " + PERSON_NAME + " (" + PERSON_ROLE + ")")
    print("=" * 60)
    print()
    print("-- SYSTEM PROMPT --")
    print()
    print(system_prompt)
    print()
    print("-- YOUR TASK --")
    print()
    print(user_prompt)
    print()
    print("=" * 60)
    print()
    print("Now run:  python3 " + str(EXCHANGE_DIR / "worker.py") + " submit << 'EOF'")
    print("...your response...")
    print("EOF")


def cmd_submit():
    """Read response from stdin, write atomically via tmp+rename."""
    text = sys.stdin.read().strip()
    if not text:
        print("ERROR: empty response, nothing submitted.")
        sys.exit(1)

    tmp_file = EXCHANGE_DIR / "response.tmp"
    final_file = EXCHANGE_DIR / "response.txt"

    tmp_file.write_text(text, encoding="utf-8")
    tmp_file.rename(final_file)

    print("OK: response submitted (" + str(len(text)) + " chars)")


def cmd_identity():
    """Print this person's identity/persona card."""
    print(IDENTITY)


def cmd_help():
    print("Usage: python3 worker.py <command>")
    print()
    print("Commands:")
    print("  poll     — Check for work. Prints request if available, or NO_WORK.")
    print("  submit   — Read response from stdin, write atomically.")
    print("  identity — Print persona card.")
    print("  help     — Show this message.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        cmd_help()
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "poll":
        cmd_poll()
    elif cmd == "submit":
        cmd_submit()
    elif cmd == "identity":
        cmd_identity()
    elif cmd == "help":
        cmd_help()
    else:
        print("Unknown command: " + cmd)
        cmd_help()
        sys.exit(1)
'''
        return template.format(
            name=person.name,
            pid=person.id,
            role=person.role,
            exchange_dir=pdir,
            persona=escaped_persona,
        )


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
