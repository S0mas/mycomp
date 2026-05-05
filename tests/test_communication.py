"""Tests for Message, Session, SessionRules, and communication patterns."""
import pytest
from unittest.mock import MagicMock

from aicompany.models import Message, Session, SessionRules, Person
from aicompany.communication import create_session, run_lead_delegates, run_pair_review, run_pattern


# ── Message ────────────────────────────────────────────────────────────────────

class TestMessage:
    def test_round_trip(self):
        m = Message(sender="alice", recipient="bob", kind="task", content="Do this")
        restored = Message.from_dict(m.to_dict())
        assert restored.sender == "alice"
        assert restored.content == "Do this"

    def test_system_factory(self):
        m = Message.system("bob", "Max rounds reached", reason="max_rounds")
        assert m.sender == "system"
        assert m.kind == "system"
        assert m.context["reason"] == "max_rounds"

    def test_auto_id_and_timestamp(self):
        m = Message(sender="a", recipient="b", kind="task", content="x")
        assert len(m.id) == 12
        assert m.timestamp


# ── SessionRules ───────────────────────────────────────────────────────────────

class TestSessionRules:
    def test_defaults(self):
        r = SessionRules()
        assert r.pattern == "lead_delegates"
        assert r.max_rounds == 3
        assert r.allow_direct is True

    def test_from_dict(self):
        r = SessionRules.from_dict({"pattern": "pair_review", "max_rounds": 5})
        assert r.pattern == "pair_review"
        assert r.max_rounds == 5

    def test_describe_includes_rules(self):
        r = SessionRules(max_rounds=3, channels=[["coder", "reviewer"]])
        text = r.describe("coder", ["coder", "reviewer", "lead"])
        assert "Max rounds: 3" in text
        assert "reviewer" in text

    def test_describe_no_direct(self):
        r = SessionRules(allow_direct=False)
        text = r.describe("coder", ["coder", "lead"])
        assert "not allowed" in text


# ── Session ────────────────────────────────────────────────────────────────────

class TestSession:
    def _make_session(self, **kwargs):
        defaults = dict(
            id="sess1", task_id="t1",
            participants=["lead", "coder", "reviewer"],
        )
        defaults.update(kwargs)
        return Session(**defaults)

    def test_can_send_basic(self):
        s = self._make_session()
        ok, _ = s.can_send("lead", "coder")
        assert ok

    def test_can_send_after_max_rounds(self):
        s = self._make_session(rules=SessionRules(max_rounds=1))
        s.round = 1
        ok, reason = s.can_send("lead", "coder")
        assert not ok
        assert "Max rounds" in reason

    def test_can_send_non_participant(self):
        s = self._make_session()
        ok, reason = s.can_send("outsider", "lead")
        assert not ok
        assert "not a participant" in reason

    def test_add_message_allowed(self):
        s = self._make_session()
        msg = Message(sender="lead", recipient="coder", kind="brief", content="Do X")
        feedback = s.add_message(msg)
        assert feedback is None
        assert len(s.messages) == 1

    def test_add_message_blocked_returns_feedback(self):
        s = self._make_session(rules=SessionRules(max_rounds=0))
        msg = Message(sender="lead", recipient="coder", kind="brief", content="Do X")
        feedback = s.add_message(msg)
        assert feedback is not None
        assert feedback.kind == "system"
        assert "not delivered" in feedback.content
        assert feedback.recipient == "lead"  # feedback goes back to sender

    def test_messages_for(self):
        s = self._make_session()
        s.add_message(Message(sender="lead", recipient="coder", kind="brief", content="Do X"))
        s.add_message(Message(sender="lead", recipient="reviewer", kind="brief", content="Review X"))
        coder_msgs = s.messages_for("coder")
        assert len(coder_msgs) == 1
        assert coder_msgs[0].content == "Do X"

    def test_messages_for_includes_team_broadcasts(self):
        s = self._make_session()
        s.add_message(Message(sender="lead", recipient="team", kind="brief", content="Team brief"))
        coder_msgs = s.messages_for("coder")
        assert len(coder_msgs) == 1

    def test_complete(self):
        s = self._make_session()
        assert not s.is_complete()
        s.complete()
        assert s.is_complete()
        assert s.status == "complete"


# ── Communication patterns ────────────────────────────────────────────────────

def _make_persons():
    lead = Person(id="lead", name="Lead", role="lead", identity="You are lead.")
    coder = Person(id="coder", name="Coder", role="coder", identity="You are coder.")
    reviewer = Person(id="reviewer", name="Reviewer", role="reviewer", identity="You review code.")
    return lead, coder, reviewer


def _make_mock_reasoner():
    mock = MagicMock()
    mock.think.return_value = "Mock output"
    return mock


class TestLeadDelegates:
    def test_produces_output(self):
        lead, coder, reviewer = _make_persons()
        session = create_session("t1", ["lead", "coder", "reviewer"])
        reasoner = _make_mock_reasoner()

        output = run_lead_delegates(
            session, lead, [lead, coder, reviewer],
            "Build API", "Build a REST API", "Python project",
            reasoner,
        )
        assert output == "Mock output"
        assert session.status == "complete"

    def test_reasoner_called_for_each_person(self):
        lead, coder, reviewer = _make_persons()
        session = create_session("t1", ["lead", "coder", "reviewer"])
        reasoner = _make_mock_reasoner()

        run_lead_delegates(
            session, lead, [lead, coder, reviewer],
            "Build API", "desc", "ctx", reasoner,
        )
        # lead brief + coder execute + reviewer execute + lead synthesize = 4
        assert reasoner.think.call_count == 4

    def test_single_person_team(self):
        lead = Person(id="lead", name="Lead", role="lead", identity="Solo lead.")
        session = create_session("t1", ["lead"])
        reasoner = _make_mock_reasoner()

        output = run_lead_delegates(
            session, lead, [lead],
            "Task", "desc", "ctx", reasoner,
        )
        assert output == "Mock output"
        # Only 1 call — lead brief, no synthesis needed
        assert reasoner.think.call_count == 1

    def test_status_callback(self):
        lead, coder, reviewer = _make_persons()
        session = create_session("t1", ["lead", "coder", "reviewer"])
        reasoner = _make_mock_reasoner()
        statuses = []

        run_lead_delegates(
            session, lead, [lead, coder, reviewer],
            "Task", "desc", "ctx", reasoner,
            on_status=lambda msg: statuses.append(msg),
        )
        assert any("Lead" in s for s in statuses)
        assert any("Coder" in s for s in statuses)


class TestPairReview:
    def test_produces_output(self):
        lead, coder, reviewer = _make_persons()
        session = create_session("t1", ["lead", "coder", "reviewer"],
                                 SessionRules(pattern="pair_review", max_rounds=5))
        reasoner = _make_mock_reasoner()

        output = run_pair_review(
            session, lead, [lead, coder, reviewer],
            "Build API", "desc", "ctx", reasoner,
        )
        assert output == "Mock output"
        assert session.status == "complete"

    def test_falls_back_without_coder(self):
        lead = Person(id="lead", name="Lead", role="lead", identity="Lead.")
        arch = Person(id="arch", name="Architect", role="architect", identity="Arch.")
        session = create_session("t1", ["lead", "arch"],
                                 SessionRules(pattern="pair_review"))
        reasoner = _make_mock_reasoner()

        output = run_pair_review(
            session, lead, [lead, arch],
            "Task", "desc", "ctx", reasoner,
        )
        assert output == "Mock output"


class TestRunPattern:
    def test_unknown_pattern_falls_back(self):
        lead, coder, reviewer = _make_persons()
        session = create_session("t1", ["lead", "coder", "reviewer"])
        reasoner = _make_mock_reasoner()

        output = run_pattern(
            "nonexistent_pattern", session, lead, [lead, coder, reviewer],
            "Task", "desc", "ctx", reasoner,
        )
        assert output == "Mock output"
        assert session.status == "complete"


class TestAgentRules:
    def test_without_workspace_returns_rules_unchanged(self):
        from aicompany.communication import _agent_rules
        assert _agent_rules("some rules", "") == "some rules"

    def test_with_workspace_appends_instructions(self):
        from aicompany.communication import _agent_rules
        result = _agent_rules("rules text", "projects/proj_abc/src")
        assert "projects/proj_abc/src" in result
        assert "write_file" in result
        assert "rules text" in result
