"""Tests for ChatSessionReasoner — per-person file exchange."""
import json
import threading
import time
from pathlib import Path

import pytest

from aicompany.models import Message, Person, Skill
from aicompany.reasoner import ChatSessionReasoner, create_reasoner


@pytest.fixture
def exchange_dir(tmp_path):
    return tmp_path / "exchange"


@pytest.fixture
def person_alice():
    return Person(
        id="alice", name="Alice", role="lead",
        identity="You are Alice, a senior architect.",
        skills=["python"], knowledge=["10 years experience"], rules=["Be concise"],
    )


@pytest.fixture
def person_bob():
    return Person(
        id="bob", name="Bob", role="coder",
        identity="You are Bob, a backend developer.",
    )


@pytest.fixture
def skill_registry():
    return {
        "python": Skill(id="python", name="Python", category="language",
                        knowledge=["Use type hints", "Follow PEP 8"]),
    }


class TestPrepareAndInstructions:
    def test_prepare_person_creates_dir_and_persona(self, exchange_dir, person_alice, skill_registry):
        r = ChatSessionReasoner(exchange_root=exchange_dir)
        pdir = r.prepare_person(person_alice, skill_registry)

        assert pdir == exchange_dir / "alice"
        assert pdir.exists()
        persona = (pdir / "persona.md").read_text()
        assert "Alice" in persona
        assert "senior architect" in persona
        assert "Use type hints" in persona
        # loop.py should be generated
        assert (pdir / "loop.py").exists()
        loop = (pdir / "loop.py").read_text()
        assert "EXCHANGE_DIR" in loop
        assert str(pdir) in loop

    def test_prepare_all(self, exchange_dir, person_alice, person_bob):
        r = ChatSessionReasoner(exchange_root=exchange_dir)
        r.prepare_all([person_alice, person_bob])

        assert (exchange_dir / "alice" / "persona.md").exists()
        assert (exchange_dir / "alice" / "loop.py").exists()
        assert (exchange_dir / "bob" / "persona.md").exists()
        assert (exchange_dir / "bob" / "loop.py").exists()

    def test_print_instructions_contains_tab_info(self, exchange_dir, person_alice, person_bob, capsys):
        r = ChatSessionReasoner(exchange_root=exchange_dir)
        r.prepare_all([person_alice, person_bob])
        text = r.print_instructions()

        assert "2 separate AI chat tab(s)" in text
        assert "Tab 1: Alice" in text
        assert "Tab 2: Bob" in text
        assert "loop.py" in text

    def test_print_instructions_empty_when_no_persons(self, exchange_dir):
        r = ChatSessionReasoner(exchange_root=exchange_dir)
        assert r.print_instructions() == ""

    def test_stale_files_cleaned(self, exchange_dir, person_alice):
        pdir = exchange_dir / "alice"
        pdir.mkdir(parents=True)
        (pdir / "WAITING").write_text("stale")
        (pdir / "request.json").write_text("{}")
        (pdir / "response.txt").write_text("old")

        r = ChatSessionReasoner(exchange_root=exchange_dir)
        r.prepare_person(person_alice)

        assert not (pdir / "WAITING").exists()
        assert not (pdir / "request.json").exists()
        assert not (pdir / "response.txt").exists()


class TestThink:
    def test_think_reads_response(self, exchange_dir, person_alice):
        r = ChatSessionReasoner(exchange_root=exchange_dir)
        pdir = exchange_dir / "alice"
        pdir.mkdir(parents=True, exist_ok=True)

        messages = [
            Message(sender="orchestrator", recipient="alice", kind="task",
                    content="Design the API"),
        ]

        # Simulate a chat AI responding after a short delay
        def respond():
            time.sleep(0.3)
            (pdir / "response.txt").write_text("Here is the API design...")

        t = threading.Thread(target=respond)
        t.start()

        result = r.think(person_alice, messages)
        t.join()

        assert result == "Here is the API design..."
        # Files should be cleaned up
        assert not (pdir / "request.json").exists()
        assert not (pdir / "response.txt").exists()
        assert not (pdir / "WAITING").exists()

    def test_think_writes_correct_request(self, exchange_dir, person_alice):
        r = ChatSessionReasoner(exchange_root=exchange_dir)
        pdir = exchange_dir / "alice"
        pdir.mkdir(parents=True, exist_ok=True)

        messages = [
            Message(sender="orchestrator", recipient="alice", kind="task",
                    content="Build the service"),
        ]

        # Respond immediately so think() doesn't block long
        def respond():
            time.sleep(0.2)
            # Read request before responding
            req = json.loads((pdir / "request.json").read_text())
            assert req["person_id"] == "alice"
            assert "Build the service" in req["user"]
            assert "Alice" in req["system"] or "architect" in req["system"]
            (pdir / "response.txt").write_text("Done")

        t = threading.Thread(target=respond)
        t.start()
        r.think(person_alice, messages)
        t.join()

    def test_think_timeout(self, exchange_dir, person_alice, monkeypatch):
        import aicompany.reasoner as mod
        monkeypatch.setattr(mod, "_TIMEOUT", 0.5)
        monkeypatch.setattr(mod, "_POLL_INTERVAL", 0.1)

        r = ChatSessionReasoner(exchange_root=exchange_dir)
        (exchange_dir / "alice").mkdir(parents=True, exist_ok=True)

        with pytest.raises(TimeoutError, match="alice"):
            r.think(person_alice, [])


class TestCreateReasoner:
    def test_chat_session_returns_chat_reasoner(self, monkeypatch):
        monkeypatch.setenv("AICOMPANY_LLM_BACKEND", "chat_session")
        from aicompany import config
        monkeypatch.setattr(config, "LLM_BACKEND", "chat_session")
        r = create_reasoner()
        assert isinstance(r, ChatSessionReasoner)

    def test_other_backend_returns_llm_reasoner(self, monkeypatch):
        from aicompany import config
        monkeypatch.setattr(config, "LLM_BACKEND", "fake")
        from aicompany.reasoner import LLMReasoner
        r = create_reasoner()
        assert isinstance(r, LLMReasoner)
