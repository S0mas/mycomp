"""
Chat-session backend -- everything needed for multi-tab AI collaboration.

Contains:
  - ChatSessionBackend: LLMBackend transport (single-dir, simple)
  - ChatSessionReasoner: per-person Reasoner with atomic poll/submit protocol

The Reasoner is the primary interface used by the orchestrator.
Configure via: AICOMPANY_LLM_BACKEND=chat_session
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from aicompany import config
from aicompany.llm_backend import Reasoner, register_backend
from aicompany.models import Message, Person, Skill, build_prompt
from aicompany.reasoner import build_system_prompt, build_user_prompt

_POLL_INTERVAL = 1.0
_TIMEOUT = int(os.environ.get("MYCOMP_CHAT_TIMEOUT", "600"))

_WORKER_TEMPLATE = (Path(__file__).parent / "worker_template.py.txt").read_text(encoding="utf-8")


# -- ChatSessionBackend (LLMBackend transport) ---------------------------------

class ChatSessionBackend:
    """LLM backend that communicates via filesystem with a chat AI session."""

    def __init__(self) -> None:
        self._exchange_dir = Path(
            os.environ.get("MYCOMP_EXCHANGE_DIR", str(config.BASE_DIR / "tmp" / "llm_exchange"))
        )
        self._exchange_dir.mkdir(parents=True, exist_ok=True)

    def call(self, system: str, user: str, max_tokens: int, model: str) -> str:
        request_file = self._exchange_dir / "request.json"
        response_file = self._exchange_dir / "response.txt"
        response_file.unlink(missing_ok=True)

        request_data = {"system": system, "user": user, "max_tokens": max_tokens, "model": model}
        request_file.write_text(json.dumps(request_data, indent=2), encoding="utf-8")

        signal = self._exchange_dir / "READY"
        tmp = self._exchange_dir / "READY.tmp"
        tmp.write_text("1", encoding="utf-8")
        tmp.rename(signal)

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
        raise TimeoutError(f"No response within {_TIMEOUT}s. Check {self._exchange_dir}")


register_backend("chat_session", ChatSessionBackend)


# -- ChatSessionReasoner -------------------------------------------------------

class ChatSessionReasoner:
    """
    Per-person Reasoner for multi-tab AI chat sessions.

    Atomic protocol (race-free):
      1. Orchestrator writes request.json, then atomically creates READY (tmp+rename)
      2. AI runs poll -> deletes READY (claims), reads request.json, prints it
      3. AI runs submit -> writes .tmp, renames to response.txt (atomic)
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

    def setup(self, persons: list[Person], skill_registry: dict[str, Skill] | None = None) -> None:
        """Prepare per-person exchange dirs and print tab instructions."""
        self.prepare_all(persons, skill_registry)
        self.print_instructions()

    def prepare_person(self, person: Person, skill_registry: dict[str, Skill] | None = None) -> Path:
        """Create exchange dir, write persona card and worker.py for a person."""
        pdir = self._root / person.id
        pdir.mkdir(parents=True, exist_ok=True)
        persona_card = self._build_persona_card(person, skill_registry)
        (pdir / "persona.md").write_text(persona_card, encoding="utf-8")
        worker_script = self._build_worker_script(person, pdir, skill_registry)
        (pdir / "worker.py").write_text(worker_script, encoding="utf-8")
        self._prepared_persons[person.id] = person
        return pdir

    def prepare_all(self, persons: list[Person], skill_registry: dict[str, Skill] | None = None) -> None:
        """Prepare exchange dirs for all persons in a team."""
        for p in persons:
            self.prepare_person(p, skill_registry)

    def print_instructions(self) -> str:
        """Return (and print) user-facing instructions for setting up AI tabs."""
        if not self._prepared_persons:
            return ""

        lines = [
            "",
            "=" * 70,
            "  CHAT SESSION SETUP",
            "=" * 70,
            "",
            f"  Open {len(self._prepared_persons)} separate AI chat tab(s).",
            "  Each AI uses worker.py (non-blocking poll/submit commands).",
            "",
            "  Protocol per AI tab:",
            "    1. python3 <dir>/worker.py identity   -- see who you are",
            "    2. python3 <dir>/worker.py poll       -- check for work",
            "    3. python3 <dir>/worker.py submit << 'EOF'",
            "       ...response...",
            "       EOF",
            "    4. Repeat from step 2.",
            "",
        ]

        for i, (pid, person) in enumerate(self._prepared_persons.items(), 1):
            pdir = self._root / pid
            lines.append(f"  Tab {i}: {person.name} ({person.role})")
            lines.append(f"    -> python3 {pdir}/worker.py poll")
            lines.append("")

        lines.append("=" * 70)
        lines.append("")

        text = "\n".join(lines)
        print(text)
        return text

    def think(
        self,
        person: Person,
        messages: list[Message],
        skill_registry: dict[str, Skill] | None = None,
        session_rules_text: str = "",
        max_tokens: int = 4096,
    ) -> str:
        """Write request to person exchange dir and wait for response."""
        pdir = self._root / person.id
        pdir.mkdir(parents=True, exist_ok=True)

        system = self._build_system(person, skill_registry, session_rules_text)
        user = self._build_user(person, messages)

        request_file = pdir / "request.json"
        response_file = pdir / "response.txt"
        ready_signal = pdir / "READY"

        response_file.unlink(missing_ok=True)
        (pdir / "response.tmp").unlink(missing_ok=True)

        request_data = {
            "system": system,
            "user": user,
            "max_tokens": max_tokens,
            "person_id": person.id,
            "person_name": person.name,
        }
        request_file.write_text(json.dumps(request_data, indent=2), encoding="utf-8")

        tmp_ready = pdir / "READY.tmp"
        tmp_ready.write_text("1", encoding="utf-8")
        tmp_ready.rename(ready_signal)

        print(f"    Waiting for response from {person.name} ({person.id})...")
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

    def _build_system(self, person: Person, skill_registry: dict[str, Skill] | None, session_rules_text: str) -> str:
        return build_system_prompt(person, skill_registry, session_rules_text)

    def _build_user(self, person: Person, messages: list[Message]) -> str:
        return build_user_prompt(person, messages)

    def _build_persona_card(self, person: Person, skill_registry: dict[str, Skill] | None) -> str:
        """Build a Markdown persona card for the chat AI tab."""
        prompt = build_prompt(person, skill_registry)
        lines = [
            f"# {person.name} (id: {person.id}, role: {person.role})",
            "",
            "## Identity",
            "",
            prompt,
            "",
            "## How this works",
            "",
            "Use worker.py in this directory (non-blocking, no stdin required):",
            "",
            "1. python3 worker.py poll -- check for work.",
            "2. Read the request, formulate your response.",
            "3. python3 worker.py submit << 'EOF'",
            "   Your response here...",
            "   EOF",
        ]
        return "\n".join(lines)

    def _build_worker_script(self, person: Person, pdir: Path, skill_registry: dict[str, Skill] | None = None) -> str:
        """Build worker.py using the template file."""
        persona_card = self._build_persona_card(person, skill_registry)
        # Use .format() on the template
        return _WORKER_TEMPLATE.format(
            name=person.name,
            pid=person.id,
            role=person.role,
            exchange_dir=pdir,
            persona=persona_card,
        )


# Verify conformance to Reasoner protocol
assert isinstance(ChatSessionReasoner.__new__(ChatSessionReasoner), Reasoner)
