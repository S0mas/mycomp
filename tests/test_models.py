"""
Tests for aicompany/models.py

What we verify:
  - Every dataclass can be constructed with minimal args
  - to_dict() / from_dict() round-trips produce equal objects
  - Helper properties (skill_set, all_skills, task_by_id) work correctly
  - Default values are sane (status='pending', tools=[], etc.)
"""
import pytest
from aicompany.models import CompanyState, ProjectPlan, Task, Team


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
