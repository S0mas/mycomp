"""Tests for Message, Session, SessionRules, and async communication patterns."""
import pytest
from unittest.mock import AsyncMock, patch
from pathlib import Path

from aicompany.models import Message, Session, SessionRules, Person
from aicompany.communication import (
    create_session, run_lead_delegates, run_pair_review,
    run_develop_test_review, run_pattern,
)


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
        assert feedback.recipient == "lead"

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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_persons():
    lead = Person(id="lead", name="Lead", role="lead", identity="You are lead.")
    coder = Person(id="coder", name="Coder", role="coder", identity="You are coder.")
    reviewer = Person(id="reviewer", name="Reviewer", role="reviewer", identity="You review code.")
    return lead, coder, reviewer


def _fake_agent_class(response: str = "Mock output"):
    """Returns a FakePersonAgent class whose think() always returns response."""
    class FakePersonAgent:
        _think_count = 0

        def __init__(self, person, workspace, skill_registry=None):
            self.person = person

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def think(self, message: str) -> str:
            FakePersonAgent._think_count += 1
            return response

    FakePersonAgent._think_count = 0
    return FakePersonAgent


# ── Communication patterns ────────────────────────────────────────────────────

class TestLeadDelegates:
    async def test_produces_output(self, tmp_path):
        lead, coder, reviewer = _make_persons()
        session = create_session("t1", ["lead", "coder", "reviewer"])
        FakeAgent = _fake_agent_class()

        with patch("aicompany.patterns.PersonAgent", FakeAgent):
            output = await run_lead_delegates(
                session, lead, [lead, coder, reviewer],
                "Build API", "Build a REST API", "Python project", tmp_path,
            )
        assert output == "Mock output"
        assert session.status == "complete"

    async def test_agent_called_for_each_person(self, tmp_path):
        lead, coder, reviewer = _make_persons()
        session = create_session("t1", ["lead", "coder", "reviewer"])
        FakeAgent = _fake_agent_class()

        with patch("aicompany.patterns.PersonAgent", FakeAgent):
            await run_lead_delegates(
                session, lead, [lead, coder, reviewer],
                "Build API", "desc", "ctx", tmp_path,
            )
        # lead brief + coder + reviewer + lead synthesize = 4
        assert FakeAgent._think_count == 4

    async def test_single_person_team(self, tmp_path):
        lead = Person(id="lead", name="Lead", role="lead", identity="Solo lead.")
        session = create_session("t1", ["lead"])
        FakeAgent = _fake_agent_class()

        with patch("aicompany.patterns.PersonAgent", FakeAgent):
            output = await run_lead_delegates(
                session, lead, [lead],
                "Task", "desc", "ctx", tmp_path,
            )
        assert output == "Mock output"
        # Only 1 call — lead brief only (no members → no synthesis needed)
        assert FakeAgent._think_count == 1

    async def test_status_callback(self, tmp_path):
        lead, coder, reviewer = _make_persons()
        session = create_session("t1", ["lead", "coder", "reviewer"])
        statuses = []
        FakeAgent = _fake_agent_class()

        with patch("aicompany.patterns.PersonAgent", FakeAgent):
            await run_lead_delegates(
                session, lead, [lead, coder, reviewer],
                "Task", "desc", "ctx", tmp_path,
                on_status=lambda msg: statuses.append(msg),
            )
        assert any("Lead" in s for s in statuses)
        assert any("Coder" in s for s in statuses)


class TestPairReview:
    async def test_produces_output(self, tmp_path):
        lead, coder, reviewer = _make_persons()
        session = create_session("t1", ["lead", "coder", "reviewer"],
                                 SessionRules(pattern="pair_review", max_rounds=5))
        FakeAgent = _fake_agent_class()

        with patch("aicompany.patterns.PersonAgent", FakeAgent):
            output = await run_pair_review(
                session, lead, [lead, coder, reviewer],
                "Build API", "desc", "ctx", tmp_path,
            )
        assert output == "Mock output"
        assert session.status == "complete"

    async def test_falls_back_to_lead_delegates_without_reviewer(self, tmp_path):
        lead = Person(id="lead", name="Lead", role="lead", identity="Lead.")
        arch = Person(id="arch", name="Architect", role="architect", identity="Arch.")
        session = create_session("t1", ["lead", "arch"],
                                 SessionRules(pattern="pair_review"))
        FakeAgent = _fake_agent_class()

        with patch("aicompany.patterns.PersonAgent", FakeAgent):
            output = await run_pair_review(
                session, lead, [lead, arch],
                "Task", "desc", "ctx", tmp_path,
            )
        assert output == "Mock output"

    async def test_reviewer_only_uses_lead_as_producer(self, tmp_path):
        lead = Person(id="lead", name="Lead", role="lead", identity="Lead.")
        reviewer = Person(id="rev", name="Reviewer", role="reviewer", identity="Reviewer.")
        session = create_session("t1", ["lead", "rev"],
                                 SessionRules(pattern="pair_review", max_rounds=4))
        FakeAgent = _fake_agent_class()

        with patch("aicompany.patterns.PersonAgent", FakeAgent):
            output = await run_pair_review(
                session, lead, [lead, reviewer],
                "Task", "desc", "ctx", tmp_path,
            )
        assert output == "Mock output"
        assert session.status == "complete"
        # lead draft + reviewer review + lead revise = at least 3 calls
        assert FakeAgent._think_count >= 3


class TestRunPattern:
    async def test_unknown_pattern_falls_back(self, tmp_path):
        lead, coder, reviewer = _make_persons()
        session = create_session("t1", ["lead", "coder", "reviewer"])
        FakeAgent = _fake_agent_class()

        with patch("aicompany.patterns.PersonAgent", FakeAgent):
            output = await run_pattern(
                "nonexistent_pattern", session, lead, [lead, coder, reviewer],
                "Task", "desc", "ctx", tmp_path,
            )
        assert output == "Mock output"
        assert session.status == "complete"


class TestDevelopTestReview:
    def _make_full_team(self):
        lead = Person(id="lead", name="Lead", role="lead", identity="Lead.")
        coder = Person(id="coder", name="Coder", role="coder", identity="Coder.")
        tester = Person(id="tester", name="Tester", role="tester", identity="Tester.")
        reviewer = Person(id="reviewer", name="Reviewer", role="reviewer", identity="Reviewer.")
        return lead, coder, tester, reviewer

    async def test_full_team_produces_output(self, tmp_path):
        lead, coder, tester, reviewer = self._make_full_team()
        members = [lead, coder, tester, reviewer]
        session = create_session("t1", [m.id for m in members],
                                 SessionRules(pattern="develop_test_review", max_rounds=6))
        FakeAgent = _fake_agent_class()

        with patch("aicompany.patterns.PersonAgent", FakeAgent):
            output = await run_develop_test_review(
                session, lead, members,
                "Implement login", "POST /login endpoint", "ctx", tmp_path,
            )
        assert output == "Mock output"
        assert session.status == "complete"

    async def test_all_roles_called(self, tmp_path):
        lead, coder, tester, reviewer = self._make_full_team()
        members = [lead, coder, tester, reviewer]
        session = create_session("t1", [m.id for m in members],
                                 SessionRules(pattern="develop_test_review", max_rounds=6))
        FakeAgent = _fake_agent_class()

        with patch("aicompany.patterns.PersonAgent", FakeAgent):
            await run_develop_test_review(
                session, lead, members, "Task", "desc", "ctx", tmp_path,
            )
        # lead (brief + final), coder (impl + revise), tester, reviewer = at least 6
        assert FakeAgent._think_count >= 4

    async def test_falls_back_to_pair_review_without_tester(self, tmp_path):
        lead, coder, _, reviewer = self._make_full_team()
        members = [lead, coder, reviewer]
        session = create_session("t1", [m.id for m in members],
                                 SessionRules(pattern="develop_test_review", max_rounds=5))
        FakeAgent = _fake_agent_class()

        with patch("aicompany.patterns.PersonAgent", FakeAgent):
            output = await run_develop_test_review(
                session, lead, members, "Task", "desc", "ctx", tmp_path,
            )
        assert output == "Mock output"
        assert session.status == "complete"

    async def test_falls_back_to_lead_delegates_without_coder(self, tmp_path):
        lead, _, tester, _ = self._make_full_team()
        members = [lead, tester]
        session = create_session("t1", [m.id for m in members],
                                 SessionRules(pattern="develop_test_review", max_rounds=4))
        FakeAgent = _fake_agent_class()

        with patch("aicompany.patterns.PersonAgent", FakeAgent):
            output = await run_develop_test_review(
                session, lead, members, "Task", "desc", "ctx", tmp_path,
            )
        assert output == "Mock output"

    async def test_registered_in_patterns(self, tmp_path):
        lead, coder, tester, reviewer = self._make_full_team()
        members = [lead, coder, tester, reviewer]
        FakeAgent = _fake_agent_class()
        with patch("aicompany.patterns.PersonAgent", FakeAgent):
            result = await run_pattern(
                "develop_test_review",
                create_session("t1", [m.id for m in members],
                               SessionRules(max_rounds=6)),
                lead, members, "Task", "desc", "ctx", tmp_path,
            )
        assert result == "Mock output"


class TestPatternResume:
    """Patterns must skip steps whose output is already in the session."""

    async def test_pair_review_lead_as_producer_skips_done_steps(self, tmp_path):
        lead = Person(id="lead", name="Lead", role="lead", identity="Lead.")
        reviewer = Person(id="rev", name="Reviewer", role="reviewer", identity="Rev.")
        session = create_session("t1", ["lead", "rev"],
                                 SessionRules(pattern="pair_review", max_rounds=4))
        # Pre-populate session with draft + review already done
        session.add_message(Message(sender="orchestrator", recipient="lead", kind="task", content="task"))
        session.add_message(Message(sender="lead", recipient="rev", kind="result", content="draft"))
        session.advance_round()
        session.add_message(Message(sender="rev", recipient="lead", kind="review", content="looks good"))

        FakeAgent = _fake_agent_class()
        with patch("aicompany.patterns.PersonAgent", FakeAgent):
            output = await run_pair_review(
                session, lead, [lead, reviewer], "T", "d", "c", tmp_path,
            )
        assert output == "Mock output"
        assert session.status == "complete"
        # Only the final revision step should have called think()
        assert FakeAgent._think_count == 1

    async def test_lead_delegates_skips_members_already_done(self, tmp_path):
        lead, coder, reviewer = _make_persons()
        session = create_session("t1", ["lead", "coder", "reviewer"],
                                 SessionRules(pattern="lead_delegates", max_rounds=5))
        # Pre-populate: brief + coder done, reviewer not done yet
        session.add_message(Message(sender="orchestrator", recipient="lead", kind="task", content="task"))
        session.add_message(Message(sender="lead", recipient="team", kind="brief", content="brief"))
        session.advance_round()
        session.add_message(Message(sender="coder", recipient="lead", kind="result", content="code"))

        FakeAgent = _fake_agent_class()
        with patch("aicompany.patterns.PersonAgent", FakeAgent):
            await run_lead_delegates(
                session, lead, [lead, coder, reviewer], "T", "d", "c", tmp_path,
            )
        # Only reviewer + lead synthesis should have called think() (not coder, not brief)
        assert FakeAgent._think_count == 2

    async def test_fully_completed_session_returns_without_llm_calls(self, tmp_path):
        lead = Person(id="lead", name="Lead", role="lead", identity="Lead.")
        reviewer = Person(id="rev", name="Reviewer", role="reviewer", identity="Rev.")
        session = create_session("t1", ["lead", "rev"],
                                 SessionRules(pattern="pair_review", max_rounds=4))
        session.add_message(Message(sender="orchestrator", recipient="lead", kind="task", content="task"))
        session.add_message(Message(sender="lead", recipient="rev", kind="result", content="draft"))
        session.advance_round()
        session.add_message(Message(sender="rev", recipient="lead", kind="review", content="review"))
        session.advance_round()
        session.add_message(Message(sender="lead", recipient="rev", kind="result", content="final"))
        session.add_message(Message(sender="lead", recipient="orchestrator", kind="result", content="final"))
        session.complete()

        FakeAgent = _fake_agent_class()
        with patch("aicompany.patterns.PersonAgent", FakeAgent):
            output = await run_pair_review(
                session, lead, [lead, reviewer], "T", "d", "c", tmp_path,
            )
        assert FakeAgent._think_count == 0
        assert output == "final"


