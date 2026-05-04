"""
Tests for aicompany/models.py

What we verify:
  - Every dataclass can be constructed with minimal args
  - to_dict() / from_dict() round-trips produce equal objects
  - Helper properties (skill_set, all_skills, task_by_id) work correctly
  - Default values are sane (status='pending', tools=[], etc.)
  - build_prompt() composes structured context correctly
"""
import pytest
from aicompany.models import CompanyState, Person, ProjectPlan, RequirementsEvaluation, Skill, Task, Team, build_prompt


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
        assert "Use type hints" in prompt              # from python skill
        assert "Use async def" in prompt               # from fastapi skill
        assert "You coordinate the backend team" in prompt  # person knowledge
        assert "Be concise in briefs" in prompt        # person rule

    def test_missing_skill_gracefully_skipped(self):
        p = Person(id="x", name="X", role="coder", identity="You are X.",
                   skills=["nonexistent"])
        prompt = build_prompt(p, {})  # skill not in registry
        assert "You are X." in prompt
        assert "Technical knowledge:" not in prompt

    def test_empty_person(self):
        p = Person(id="x", name="X", role="coder", identity="")
        prompt = build_prompt(p)
        assert prompt == ""


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
        assert t.created_at  # non-empty ISO timestamp

    def test_skill_set_is_lowercase(self):
        t = Team(id="x", name="X", skills=["Python", "FastAPI"], members=["p1"], lead_id="p1")
        assert t.skill_set == {"python", "fastapi"}

    def test_from_dict_tolerates_missing_optional_fields(self):
        t = Team.from_dict({"id": "y", "name": "Y", "skills": ["go"], "members": ["p1"], "lead_id": "p1"})
        assert t.created_at  # should have a default


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


class TestTask:
    def test_round_trip(self, sample_tasks):
        for task in sample_tasks:
            restored = Task.from_dict(task.to_dict())
            assert restored.id == task.id
            assert restored.title == task.title
            assert restored.depends_on == task.depends_on
            assert restored.is_checkpoint == task.is_checkpoint

    def test_defaults(self):
        t = Task(id="t", title="T", description="d", assigned_team="eng")
        assert t.status == "pending"
        assert t.depends_on == []
        assert t.is_checkpoint is False
        assert t.output_file == ""

    def test_from_dict_missing_optional(self):
        t = Task.from_dict({
            "id": "t1", "title": "T", "description": "d", "assigned_team": "eng"
        })
        assert t.depends_on == []
        assert t.is_checkpoint is False


class TestProjectPlan:
    def test_round_trip(self, sample_plan):
        restored = ProjectPlan.from_dict(sample_plan.to_dict())
        assert restored.project_id == sample_plan.project_id
        assert restored.title == sample_plan.title
        assert len(restored.tasks) == len(sample_plan.tasks)
        assert restored.tasks[0].id == sample_plan.tasks[0].id

    def test_task_by_id_found(self, sample_plan):
        t = sample_plan.task_by_id("task_002")
        assert t is not None
        assert t.title == "Implement API"

    def test_task_by_id_not_found(self, sample_plan):
        assert sample_plan.task_by_id("task_999") is None

    def test_defaults(self):
        p = ProjectPlan(project_id="p", title="T")
        assert p.status == "pending"
        assert p.tasks == []
        assert p.tech_stack == []
        assert p.decisions_log == []


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
