"""Tests for aicompany/workflow.py"""
from unittest.mock import patch, MagicMock

import pytest

from aicompany.workflow import evaluate_and_gate, plan_and_create_project, EvaluationResult
from aicompany import config, registry
from aicompany.models import CompanyState
from tests.conftest import write_state, write_team, write_persons


MOCK_EVAL_GOOD = {
    "clarity": 4, "completeness": 4, "feasibility": 5,
    "risks": [], "suggestions": [], "summary": "Looks good.", "verdict": "proceed",
}

MOCK_EVAL_BAD = {
    "clarity": 1, "completeness": 2, "feasibility": 1,
    "risks": ["No spec"], "suggestions": ["Add spec"], "summary": "Bad.", "verdict": "reject",
}

MOCK_CTO = {
    "title": "Test Project",
    "tech_stack": ["python"],
    "teams_required": ["backend_engineer"],
    "tasks": [
        {"id": "task_001", "title": "Do thing", "description": "Do the thing",
         "assigned_team": "backend_engineer", "depends_on": [], "is_checkpoint": False},
    ],
}


class TestEvaluateAndGate:
    def test_good_requirements_not_blocked(self):
        with patch("aicompany.workflow.llm") as m:
            m.evaluate_requirements.return_value = MOCK_EVAL_GOOD
            result = evaluate_and_gate("Build a REST API", "teams: []")
        assert not result.blocked
        assert result.evaluation.verdict == "proceed"

    def test_bad_requirements_blocked(self):
        with patch("aicompany.workflow.llm") as m:
            m.evaluate_requirements.return_value = MOCK_EVAL_BAD
            result = evaluate_and_gate("x", "teams: []")
        assert result.blocked
        assert len(result.blockers) > 0

    def test_single_low_dimension_blocks(self):
        low_clarity = {**MOCK_EVAL_GOOD, "clarity": 2}
        with patch("aicompany.workflow.llm") as m:
            m.evaluate_requirements.return_value = low_clarity
            result = evaluate_and_gate("vague", "teams: []")
        assert result.blocked
        assert any("Clarity" in b for b in result.blockers)

    def test_reject_verdict_blocks(self):
        reject = {**MOCK_EVAL_GOOD, "verdict": "reject"}
        with patch("aicompany.workflow.llm") as m:
            m.evaluate_requirements.return_value = reject
            result = evaluate_and_gate("nonsense", "teams: []")
        assert result.blocked


class TestPlanAndCreateProject:
    @pytest.fixture(autouse=True)
    def _setup(self, sample_state, sample_team, sample_persons):
        write_state(sample_state)
        write_team(sample_team)
        write_persons(sample_persons)

    def test_creates_project(self, sample_state):
        with patch("aicompany.workflow.llm") as m:
            m.cto_analyze.return_value = MOCK_CTO
            result = plan_and_create_project("Build API", "teams: []")
        assert result.project_id.startswith("proj_")
        assert result.plan.title == "Test Project"

    def test_creates_missing_teams(self, sample_state):
        cto_needing_new = {**MOCK_CTO, "teams_required": ["backend_engineer", "new_team"]}
        hr_response = {
            "team": {"id": "new_team", "name": "New", "skills": [], "members": ["new_lead"], "lead_id": "new_lead"},
            "persons": [{"id": "new_lead", "name": "Lead", "role": "lead", "identity": "You lead.", "skills": [], "knowledge": [], "rules": [], "tools": []}],
            "skills": [],
        }
        with patch("aicompany.workflow.llm") as m:
            m.cto_analyze.return_value = cto_needing_new
            m.hr_create_team.return_value = hr_response
            result = plan_and_create_project("Build API", "teams: []")
        assert "new_team" in result.created_teams

    def test_status_callback_called(self, sample_state):
        statuses = []
        with patch("aicompany.workflow.llm") as m:
            m.cto_analyze.return_value = MOCK_CTO
            plan_and_create_project("Build API", "teams: []", on_status=statuses.append)
        assert any("CTO" in s for s in statuses)
