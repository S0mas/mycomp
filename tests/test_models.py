"""
Tests for aicompany/models.py

What we verify:
  - Every dataclass can be constructed with minimal args
  - to_dict() / from_dict() round-trips produce equal objects
  - Helper properties (skill_set, all_skills, task_by_id, sub_requirement_by_id) work correctly
  - Default values are sane (status='pending', tools=[], etc.)
  - build_prompt() composes structured context correctly
  - TaskInput.validate() enforces specification rules
  - Plan/Task recursive serialization is depth-bounded
  - Backward compat: old plan.yaml 'description' key is accepted by Task.from_dict()
"""
import pytest
from aicompany.models import (
    CompanyState, Person, Plan, ProjectPlan, Requirement, RequirementTest,
    RequirementsEvaluation, Skill, SubRequirement, Task, TaskInput, Team,
    RequirementTestSuite, MAX_PLAN_DEPTH, build_prompt,
)
from tests.conftest import make_leaf_plan, make_task_input


# ── TaskInput ─────────────────────────────────────────────────────────────────

class TestTaskInput:
    def test_round_trip(self):
        ti = TaskInput(specification="Build a login endpoint.", context="Part of auth project.")
        restored = TaskInput.from_dict(ti.to_dict())
        assert restored.specification == ti.specification
        assert restored.context == ti.context

    def test_defaults(self):
        ti = TaskInput(specification="Do something meaningful here.")
        assert ti.context == ""

    def test_validate_valid(self):
        ti = TaskInput(specification="Build a REST API with login and registration endpoints.")
        assert ti.validate() == []

    def test_validate_empty(self):
        errors = TaskInput(specification="").validate()
        assert any("empty" in e.lower() for e in errors)

    def test_validate_whitespace_only(self):
        errors = TaskInput(specification="   ").validate()
        assert any("empty" in e.lower() for e in errors)

    def test_validate_too_short(self):
        errors = TaskInput(specification="Too short").validate()
        assert any("short" in e.lower() for e in errors)

    def test_validate_null_bytes(self):
        errors = TaskInput(specification="A" * 60 + "\x00").validate()
        assert any("binary" in e.lower() for e in errors)

    def test_validate_does_not_check_context(self):
        # context is informational — never validated regardless of content
        ti = TaskInput(
            specification="Build a full authentication system with OAuth2 and JWT tokens.",
            context="",   # empty context is fine
        )
        assert ti.validate() == []

    def test_from_dict_accepts_legacy_text_key(self):
        ti = TaskInput.from_dict({"text": "Old format specification value here."})
        assert ti.specification == "Old format specification value here."

    def test_from_dict_prefers_specification_over_text(self):
        ti = TaskInput.from_dict({"specification": "New", "text": "Old"})
        assert ti.specification == "New"


# ── Skill ─────────────────────────────────────────────────────────────────────

class TestSkill:
    def test_round_trip(self):
        s = Skill(id="python", name="Python", category="language",
                  knowledge=["Use type hints"])
        restored = Skill.from_dict(s.to_dict())
        assert restored.id == s.id
        assert restored.knowledge == s.knowledge
        assert restored.category == s.category

    def test_defaults(self):
        s = Skill(id="x", name="X")
        assert s.category == ""
        assert s.knowledge == []
        assert s.created_at

    def test_from_dict_tolerates_missing_optional(self):
        s = Skill.from_dict({"id": "y", "name": "Y"})
        assert s.knowledge == []
        assert s.category == ""


# ── Person ────────────────────────────────────────────────────────────────────

class TestPerson:
    def test_round_trip(self, sample_persons):
        for person in sample_persons:
            restored = Person.from_dict(person.to_dict())
            assert restored.id == person.id
            assert restored.identity == person.identity
            assert restored.skills == person.skills
            assert restored.knowledge == person.knowledge
            assert restored.rules == person.rules

    def test_defaults(self):
        p = Person(id="x", name="X", role="coder", identity="You are X.")
        assert p.skills == []
        assert p.knowledge == []
        assert p.rules == []
        assert p.tools == []
        assert p.created_at

    def test_from_dict_tolerates_missing_optional(self):
        p = Person.from_dict({"id": "y", "name": "Y", "role": "coder", "identity": "You are Y."})
        assert p.skills == []
        assert p.knowledge == []
        assert p.rules == []


# ── build_prompt ──────────────────────────────────────────────────────────────

class TestBuildPrompt:
    def test_identity_only(self):
        p = Person(id="x", name="X", role="coder", identity="You are X.")
        prompt = build_prompt(p)
        assert "You are X." in prompt

    def test_includes_skill_knowledge(self):
        p = Person(id="x", name="X", role="coder", identity="You are X.",
                   skills=["python"])
        skills = {"python": Skill(id="python", name="Python",
                                  knowledge=["Use type hints"])}
        prompt = build_prompt(p, skills)
        assert "Use type hints" in prompt
        assert "Technical knowledge:" in prompt

    def test_includes_person_knowledge(self):
        p = Person(id="x", name="X", role="coder", identity="You are X.",
                   knowledge=["I know databases"])
        prompt = build_prompt(p)
        assert "I know databases" in prompt
        assert "Your experience:" in prompt

    def test_includes_rules(self):
        p = Person(id="x", name="X", role="coder", identity="You are X.",
                   rules=["Write complete code"])
        prompt = build_prompt(p)
        assert "Write complete code" in prompt
        assert "Rules you follow:" in prompt

    def test_full_prompt_composition(self, sample_persons, sample_skills):
        person = sample_persons[0]  # be_lead with skills, knowledge, rules
        skill_registry = {s.id: s for s in sample_skills}
        prompt = build_prompt(person, skill_registry)
        assert "You are a backend lead." in prompt
        assert "Use type hints" in prompt
        assert "Use async def" in prompt
        assert "You coordinate the backend team" in prompt
        assert "Be concise in briefs" in prompt

    def test_missing_skill_gracefully_skipped(self):
        p = Person(id="x", name="X", role="coder", identity="You are X.",
                   skills=["nonexistent"])
        prompt = build_prompt(p, {})
        assert "You are X." in prompt
        assert "Technical knowledge:" not in prompt

    def test_empty_person(self):
        p = Person(id="x", name="X", role="coder", identity="")
        prompt = build_prompt(p)
        assert prompt == ""


# ── Team ──────────────────────────────────────────────────────────────────────

class TestTeam:
    def test_round_trip(self, sample_team):
        restored = Team.from_dict(sample_team.to_dict())
        assert restored.id == sample_team.id
        assert restored.name == sample_team.name
        assert restored.skills == sample_team.skills
        assert restored.members == sample_team.members
        assert restored.lead_id == sample_team.lead_id

    def test_defaults(self):
        t = Team(id="x", name="X", skills=[], members=["p1"], lead_id="p1")
        assert t.created_at

    def test_skill_set_is_lowercase(self):
        t = Team(id="x", name="X", skills=["Python", "FastAPI"], members=["p1"], lead_id="p1")
        assert t.skill_set == {"python", "fastapi"}

    def test_from_dict_tolerates_missing_optional_fields(self):
        t = Team.from_dict({"id": "y", "name": "Y", "skills": ["go"], "members": ["p1"], "lead_id": "p1"})
        assert t.created_at


# ── CompanyState ──────────────────────────────────────────────────────────────

class TestCompanyState:
    def test_round_trip(self, sample_state):
        restored = CompanyState.from_dict(sample_state.to_dict())
        assert restored.version == sample_state.version
        assert restored.teams == sample_state.teams
        assert restored.technologies_seen == sample_state.technologies_seen

    def test_defaults(self):
        s = CompanyState()
        assert s.version == "1"
        assert s.teams == []
        assert s.technologies_seen == []

    def test_team_ids(self, sample_state):
        assert "backend_engineer" in sample_state.team_ids()

    def test_all_skills(self, sample_state):
        skills = sample_state.all_skills()
        assert "python" in skills
        assert "fastapi" in skills

    def test_all_skills_empty_state(self):
        assert CompanyState().all_skills() == set()


# ── Task ──────────────────────────────────────────────────────────────────────

class TestTask:
    def test_round_trip(self, sample_tasks):
        for task in sample_tasks:
            restored = Task.from_dict(task.to_dict())
            assert restored.id == task.id
            assert restored.title == task.title
            assert restored.input.specification == task.input.specification
            assert restored.input.context == task.input.context
            assert restored.depends_on == task.depends_on
            assert restored.is_checkpoint == task.is_checkpoint
            assert restored.plan.has_subtasks == task.plan.has_subtasks

    def test_defaults(self):
        t = Task(
            id="t", title="T",
            input=make_task_input("Do something meaningful for the project."),
            assigned_team="eng",
            plan=make_leaf_plan("T"),
        )
        assert t.status == "pending"
        assert t.depends_on == []
        assert t.is_checkpoint is False
        assert t.output_file == ""

    def test_plan_always_present(self):
        t = Task(
            id="t", title="T",
            input=make_task_input("Something"),
            assigned_team="eng",
            plan=make_leaf_plan(),
        )
        assert t.plan is not None
        assert not t.plan.has_subtasks

    def test_backward_compat_description_key(self):
        # Legacy plan.yaml uses 'description' string instead of 'input' dict
        t = Task.from_dict({
            "id": "t1", "title": "T", "description": "old style description",
            "assigned_team": "eng"
        })
        assert t.input.specification == "old style description"
        assert t.input.context == ""
        assert not t.plan.has_subtasks   # stubs a leaf plan

    def test_from_dict_new_format(self):
        t = Task.from_dict({
            "id": "t1", "title": "T",
            "input": {"specification": "new style", "context": "some context"},
            "assigned_team": "eng",
            "plan": {"project_id": "", "title": "t plan",
                     "input": {"specification": "new style", "context": ""},
                     "requirements": [], "tasks": []},
        })
        assert t.input.specification == "new style"
        assert t.input.context == "some context"
        assert not t.plan.has_subtasks


# ── Plan ─────────────────────────────────────────────────────────────────────

class TestPlan:
    def test_round_trip(self, sample_plan):
        restored = Plan.from_dict(sample_plan.to_dict())
        assert restored.project_id == sample_plan.project_id
        assert restored.title == sample_plan.title
        assert restored.input.specification == sample_plan.input.specification
        assert len(restored.tasks) == len(sample_plan.tasks)
        assert restored.tasks[0].id == sample_plan.tasks[0].id

    def test_task_by_id_found(self, sample_plan):
        t = sample_plan.task_by_id("task_002")
        assert t is not None
        assert t.title == "Implement API"

    def test_task_by_id_not_found(self, sample_plan):
        assert sample_plan.task_by_id("task_999") is None

    def test_defaults(self):
        p = Plan(project_id="p", title="T", input=TaskInput(specification="spec"))
        assert p.status == "pending"
        assert p.tasks == []
        assert p.tech_stack == []
        assert p.decisions_log == []

    def test_has_subtasks_false_for_leaf(self):
        p = Plan(project_id="p", title="T", input=TaskInput(specification="s"), tasks=[])
        assert p.has_subtasks is False

    def test_has_subtasks_true_when_tasks_present(self, sample_plan):
        assert sample_plan.has_subtasks is True

    def test_projectplan_alias(self):
        # ProjectPlan must remain a usable alias for Plan
        p = ProjectPlan(project_id="p", title="T", input=TaskInput(specification="s"))
        assert isinstance(p, Plan)

    def test_depth_limit_raises_on_serialization(self):
        # Build a plan nested just beyond MAX_PLAN_DEPTH
        inner = Plan(project_id="", title="leaf", input=TaskInput(specification="s"),
                     tasks=[])
        for _ in range(MAX_PLAN_DEPTH + 1):
            task = Task(
                id="t", title="T",
                input=make_task_input("s"),
                assigned_team="eng",
                plan=inner,
            )
            inner = Plan(project_id="", title="wrap", input=TaskInput(specification="s"),
                         tasks=[task])
        with pytest.raises(ValueError, match="maximum depth"):
            inner.to_dict()


# ── RequirementsEvaluation ────────────────────────────────────────────────────

class TestRequirementsEvaluation:
    def test_overall_score(self):
        ev = RequirementsEvaluation(clarity=4, completeness=3, feasibility=5,
                                    risks=[], suggestions=[], summary="ok", verdict="proceed")
        assert ev.overall_score == 4.0

    def test_has_risks(self):
        ev = RequirementsEvaluation(clarity=3, completeness=3, feasibility=3,
                                    risks=["risk1"], suggestions=[], summary="", verdict="needs_work")
        assert ev.has_risks is True

    def test_no_risks(self):
        ev = RequirementsEvaluation(clarity=3, completeness=3, feasibility=3,
                                    risks=[], suggestions=[], summary="", verdict="proceed")
        assert ev.has_risks is False

    def test_from_dict(self):
        d = {"clarity": 4, "completeness": 5, "feasibility": 3,
             "risks": ["r"], "suggestions": ["s"], "summary": "sum", "verdict": "proceed"}
        ev = RequirementsEvaluation.from_dict(d)
        assert ev.clarity == 4
        assert ev.risks == ["r"]


# ── Requirements traceability models ──────────────────────────────────────────

class TestSubRequirement:
    def test_round_trip(self):
        sub = SubRequirement(
            id="REQ-0001-001", parent_id="REQ-0001",
            title="User login", description="User can log in with email.",
            acceptance_criteria=["POST /login returns 200"],
        )
        restored = SubRequirement.from_dict(sub.to_dict())
        assert restored.id == sub.id
        assert restored.parent_id == sub.parent_id
        assert restored.acceptance_criteria == sub.acceptance_criteria

    def test_defaults(self):
        sub = SubRequirement.from_dict({
            "id": "REQ-0001-001", "parent_id": "REQ-0001",
            "title": "T", "description": "D",
        })
        assert sub.acceptance_criteria == []
        assert sub.status == "pending"


class TestRequirement:
    def _make_req(self):
        return {
            "id": "REQ-0001",
            "title": "Authentication",
            "description": "Users must log in.",
            "sub_requirements": [
                {"id": "REQ-0001-001", "title": "Login", "description": "Login works.",
                 "acceptance_criteria": ["POST /login returns 200"]},
                {"id": "REQ-0001-002", "title": "Logout", "description": "Logout works.",
                 "acceptance_criteria": []},
            ],
        }

    def test_round_trip(self):
        req = Requirement.from_dict(self._make_req())
        restored = Requirement.from_dict(req.to_dict())
        assert restored.id == "REQ-0001"
        assert len(restored.sub_requirements) == 2
        assert restored.sub_requirements[0].id == "REQ-0001-001"

    def test_parent_id_injected(self):
        req = Requirement.from_dict(self._make_req())
        for sub in req.sub_requirements:
            assert sub.parent_id == "REQ-0001"

    def test_all_sub_ids(self):
        req = Requirement.from_dict(self._make_req())
        assert req.all_sub_ids() == ["REQ-0001-001", "REQ-0001-002"]

    def test_defaults(self):
        req = Requirement.from_dict({"id": "REQ-0001", "title": "T", "description": "D"})
        assert req.sub_requirements == []
        assert req.status == "pending"


class TestRequirementTest:
    def test_round_trip(self):
        rt = RequirementTest(
            id="TEST-0001-001", sub_req_id="REQ-0001-001",
            title="Login test", test_file="tests/requirements/test_REQ_0001_001.py",
        )
        restored = RequirementTest.from_dict(rt.to_dict())
        assert restored.id == rt.id
        assert restored.test_file == rt.test_file

    def test_defaults(self):
        rt = RequirementTest.from_dict({
            "id": "TEST-0001-001", "sub_req_id": "REQ-0001-001", "title": "T", "test_file": "f.py",
        })
        assert rt.status == "pending"


class TestRequirementTestSuite:
    def test_round_trip(self):
        suite = RequirementTestSuite(
            id="SUITE-0001", requirement_id="REQ-0001",
            name="Auth Test Suite", test_ids=["TEST-0001-001", "TEST-0001-002"],
        )
        restored = RequirementTestSuite.from_dict(suite.to_dict())
        assert restored.id == suite.id
        assert restored.test_ids == suite.test_ids

    def test_defaults(self):
        suite = RequirementTestSuite.from_dict({
            "id": "SUITE-0001", "requirement_id": "REQ-0001", "name": "S",
        })
        assert suite.test_ids == []
        assert suite.status == "pending"


# ── Plan with requirements ────────────────────────────────────────────────────

class TestPlanRequirements:
    def test_requirements_round_trip(self):
        req_data = {
            "id": "REQ-0001", "title": "Auth", "description": "Login.",
            "sub_requirements": [
                {"id": "REQ-0001-001", "title": "Login", "description": "Can log in.",
                 "acceptance_criteria": ["200 OK"]}
            ],
        }
        plan = Plan(
            project_id="p1", title="T",
            input=TaskInput(specification="Auth requirements"),
            requirements=[Requirement.from_dict(req_data)],
        )
        restored = Plan.from_dict(plan.to_dict())
        assert len(restored.requirements) == 1
        assert restored.requirements[0].id == "REQ-0001"

    def test_sub_requirement_by_id(self):
        req_data = {
            "id": "REQ-0001", "title": "Auth", "description": ".",
            "sub_requirements": [
                {"id": "REQ-0001-001", "title": "Login", "description": ".",
                 "acceptance_criteria": []},
            ],
        }
        plan = Plan(
            project_id="p1", title="T",
            input=TaskInput(specification="spec"),
            requirements=[Requirement.from_dict(req_data)],
        )
        sub = plan.sub_requirement_by_id("REQ-0001-001")
        assert sub is not None
        assert sub.title == "Login"
        assert plan.sub_requirement_by_id("REQ-9999") is None

    def test_task_requirements_live_in_plan(self):
        req_data = {
            "id": "REQ-0001", "title": "Auth", "description": ".",
            "sub_requirements": [
                {"id": "REQ-0001-001", "title": "Login", "description": ".", "acceptance_criteria": []},
            ],
        }
        task_plan = Plan(
            project_id="", title="task plan",
            input=TaskInput(specification="implement auth"),
            requirements=[Requirement.from_dict(req_data)],
            tasks=[],
        )
        task = Task(
            id="task_001", title="Auth task",
            input=make_task_input("implement auth"),
            assigned_team="backend_team",
            plan=task_plan,
        )
        assert len(task.plan.requirements) == 1
        assert task.plan.requirements[0].id == "REQ-0001"
