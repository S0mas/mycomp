"""Tests for aicompany/evaluation.py and aicompany/planning.py"""
import json
from unittest.mock import patch, MagicMock

import pytest

from aicompany.evaluation import evaluate_and_gate, EvaluationResult
from aicompany.planning import plan_and_create_project
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
    "requirements": [],
    "tasks": [
        {"id": "task_001", "title": "Do thing", "description": "Do the thing",
         "assigned_team": "backend_engineer", "depends_on": [], "is_checkpoint": False,
         "requirement_ids": []},
    ],
}


class TestEvaluateAndGate:
    """evaluate_and_gate loads state internally — tests write state before calling."""

    def _gate(self, requirements_text, eval_response):
        registry.save_state(CompanyState())
        with patch("aicompany.evaluation.llm") as m:
            m.evaluate_requirements.return_value = eval_response
            return evaluate_and_gate(requirements_text)

    def test_good_requirements_not_blocked(self):
        result = self._gate("Build a REST API", MOCK_EVAL_GOOD)
        assert not result.blocked
        assert result.evaluation.verdict == "proceed"

    def test_bad_requirements_blocked(self):
        result = self._gate("x", MOCK_EVAL_BAD)
        assert result.blocked
        assert len(result.blockers) > 0

    def test_single_low_dimension_blocks(self):
        low_clarity = {**MOCK_EVAL_GOOD, "clarity": 2}
        result = self._gate("vague", low_clarity)
        assert result.blocked
        assert any("Clarity" in b for b in result.blockers)

    def test_reject_verdict_blocks(self):
        reject = {**MOCK_EVAL_GOOD, "verdict": "reject"}
        result = self._gate("nonsense", reject)
        assert result.blocked


class TestPlanAndCreateProject:
    @pytest.fixture(autouse=True)
    def _setup(self, sample_state, sample_team, sample_persons):
        write_state(sample_state)
        write_team(sample_team)
        write_persons(sample_persons)

    def _plan(self, cto_response=None, hr_response=None, on_status=None):
        """Helper: mock _run_cto_planning and hr_create_team, then call plan_and_create_project."""
        cto_resp = cto_response or MOCK_CTO
        hr_resp = hr_response or {
            "team": {"id": "backend_engineer", "name": "BE", "skills": [], "members": ["be_lead"], "lead_id": "be_lead"},
            "persons": [{"id": "be_lead", "name": "Lead", "role": "lead", "identity": "You lead.", "skills": [], "knowledge": [], "rules": [], "tools": []}],
            "skills": [],
        }
        with patch("aicompany.planning._run_cto_planning", return_value=cto_resp), \
             patch("aicompany.planning.llm") as m:
            m.hr_create_team.return_value = hr_resp
            kwargs = {}
            if on_status is not None:
                kwargs["on_status"] = on_status
            return plan_and_create_project("Build API", **kwargs), m

    def test_creates_project(self):
        result, _ = self._plan()
        assert result.project_id.startswith("proj_")
        assert result.plan.title == "Test Project"

    def test_creates_missing_teams(self):
        cto_needing_new = {**MOCK_CTO, "teams_required": ["backend_engineer", "new_team"]}
        result, mock_llm = self._plan(cto_response=cto_needing_new)
        assert "new_team" in result.created_teams
        assert mock_llm.hr_create_team.called

    def test_no_hr_for_existing_team(self, sample_team):
        """When CTO requests a team that already exists in state, HR must not be called."""
        cto_using_existing = {**MOCK_CTO, "teams_required": [sample_team.id]}
        result, mock_llm = self._plan(cto_response=cto_using_existing)
        mock_llm.hr_create_team.assert_not_called()
        assert result.created_teams == []

    def test_status_callback_called(self):
        statuses = []
        cto_needing_new = {**MOCK_CTO, "teams_required": ["new_team"]}
        self._plan(cto_response=cto_needing_new, on_status=statuses.append)
        assert any("new_team" in s for s in statuses)

    def test_requirements_parsed_from_cto_output(self):
        cto_with_reqs = {
            **MOCK_CTO,
            "requirements": [
                {
                    "id": "REQ-0001",
                    "title": "User auth",
                    "description": "Auth is needed.",
                    "sub_requirements": [
                        {"id": "REQ-0001-001", "title": "Login", "description": "User can log in.",
                         "acceptance_criteria": ["Given valid creds → 200"]},
                    ],
                }
            ],
        }
        result, _ = self._plan(cto_response=cto_with_reqs)
        assert len(result.plan.requirements) == 1
        assert result.plan.requirements[0].id == "REQ-0001"
        assert len(result.plan.requirements[0].sub_requirements) == 1
