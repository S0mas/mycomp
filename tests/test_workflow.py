"""Tests for aicompany/planning.py"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from aicompany.planning import plan_and_create_project
from aicompany import registry
from tests.conftest import write_state, write_team, write_persons


def _make_val_mock():
    """Return a mock ValidationProcess instance whose run() passes the artifact through."""
    def _passthrough(artifact, on_status=None):
        return artifact, MagicMock(approved=True, rejected=False)
    return MagicMock(run=AsyncMock(side_effect=_passthrough))


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


class TestPlanAndCreateProject:
    @pytest.fixture(autouse=True)
    def _setup(self, sample_state, sample_team, sample_persons):
        write_state(sample_state)
        write_team(sample_team)
        write_persons(sample_persons)

    async def _plan(self, cto_response=None, hr_response=None, on_status=None):
        cto_resp = cto_response or MOCK_CTO
        hr_resp = hr_response or {
            "team": {"id": "backend_engineer", "name": "BE", "skills": [],
                     "members": ["be_lead"], "lead_id": "be_lead"},
            "persons": [{"id": "be_lead", "name": "Lead", "role": "lead",
                         "identity": "You lead.", "skills": [], "knowledge": [],
                         "rules": [], "tools": []}],
            "skills": [],
        }
        with patch("aicompany.planning._run_cto_planning", new=AsyncMock(return_value=cto_resp)), \
             patch("aicompany.planning._hr_create_team", new=AsyncMock(return_value=hr_resp)), \
             patch("aicompany.planning.RequirementsValidation", return_value=_make_val_mock()), \
             patch("aicompany.planning.PlanValidation", return_value=_make_val_mock()):
            kwargs = {"on_status": on_status} if on_status is not None else {}
            return await plan_and_create_project("Build API", **kwargs)

    async def test_creates_project(self):
        result = await self._plan()
        assert result.project_id.startswith("proj_")
        assert result.plan.title == "Test Project"

    async def test_creates_missing_teams(self):
        cto_needing_new = {**MOCK_CTO, "teams_required": ["backend_engineer", "new_team"]}
        mock_hr = AsyncMock(return_value={
            "team": {"id": "new_team", "name": "New", "skills": [],
                     "members": ["n_lead"], "lead_id": "n_lead"},
            "persons": [{"id": "n_lead", "name": "Lead", "role": "lead",
                         "identity": "Lead.", "skills": [], "knowledge": [],
                         "rules": [], "tools": []}],
            "skills": [],
        })
        with patch("aicompany.planning._run_cto_planning",
                   new=AsyncMock(return_value=cto_needing_new)), \
             patch("aicompany.planning._hr_create_team", new=mock_hr), \
             patch("aicompany.planning.RequirementsValidation", return_value=_make_val_mock()), \
             patch("aicompany.planning.PlanValidation", return_value=_make_val_mock()):
            result = await plan_and_create_project("Build API")
        assert "new_team" in result.created_teams
        mock_hr.assert_called()

    async def test_no_hr_for_existing_team(self, sample_team):
        cto_using_existing = {**MOCK_CTO, "teams_required": [sample_team.id]}
        mock_hr = AsyncMock()
        with patch("aicompany.planning._run_cto_planning",
                   new=AsyncMock(return_value=cto_using_existing)), \
             patch("aicompany.planning._hr_create_team", new=mock_hr), \
             patch("aicompany.planning.RequirementsValidation", return_value=_make_val_mock()), \
             patch("aicompany.planning.PlanValidation", return_value=_make_val_mock()):
            result = await plan_and_create_project("Build API")
        mock_hr.assert_not_called()
        assert result.created_teams == []

    async def test_status_callback_called(self):
        statuses = []
        cto_needing_new = {**MOCK_CTO, "teams_required": ["new_team"]}
        hr_resp = {
            "team": {"id": "new_team", "name": "New", "skills": [],
                     "members": ["n_lead"], "lead_id": "n_lead"},
            "persons": [{"id": "n_lead", "name": "Lead", "role": "lead",
                         "identity": "Lead.", "skills": [], "knowledge": [],
                         "rules": [], "tools": []}],
            "skills": [],
        }
        with patch("aicompany.planning._run_cto_planning",
                   new=AsyncMock(return_value=cto_needing_new)), \
             patch("aicompany.planning._hr_create_team", new=AsyncMock(return_value=hr_resp)), \
             patch("aicompany.planning.RequirementsValidation", return_value=_make_val_mock()), \
             patch("aicompany.planning.PlanValidation", return_value=_make_val_mock()):
            await plan_and_create_project("Build API", on_status=statuses.append)
        assert any("new_team" in s for s in statuses)

    async def test_requirements_parsed_from_cto_output(self):
        cto_with_reqs = {
            **MOCK_CTO,
            "requirements": [{
                "id": "REQ-0001", "title": "User auth", "description": "Auth needed.",
                "sub_requirements": [
                    {"id": "REQ-0001-001", "title": "Login", "description": "User can log in.",
                     "acceptance_criteria": ["Given valid creds → 200"]},
                ],
            }],
        }
        result = await self._plan(cto_response=cto_with_reqs)
        assert len(result.plan.requirements) == 1
        assert result.plan.requirements[0].id == "REQ-0001"
