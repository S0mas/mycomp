"""
Tests for aicompany/planning.py

What we verify:
  - _validate_hr_result raises on structural problems (empty members, bad lead_id,
    invalid role, empty identity)
  - _validate_hr_result passes on well-formed HR output
  - _create_missing_teams skips already-existing teams
  - _create_missing_teams calls HR for missing teams and persists them
  - _create_missing_teams propagates validation errors from _validate_hr_result
  - _build_task_tree calls _create_missing_teams for sub-plan teams_required
    when a task signals subtasks (Issue 1 fix)
"""
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from aicompany import config, registry
from aicompany.models import CompanyState, Plan, Requirement, SessionRules, TaskInput, TaskStub, Team, Person
from aicompany.planning import (
    CTOPlanning,
    _validate_hr_result,
    _create_missing_teams,
    _build_task_tree,
)
from tests.conftest import write_state, write_team, write_persons


# ── _validate_hr_result ────────────────────────────────────────────────────────

class TestValidateHrResult:
    def _valid(self, **overrides):
        base = {
            "team": {
                "id": "eng_team",
                "name": "Engineering",
                "members": ["eng_lead", "eng_coder"],
                "lead_id": "eng_lead",
                "skills": [],
            },
            "persons": [
                {"id": "eng_lead", "name": "Lead", "role": "lead",
                 "identity": "You are the lead.", "skills": [], "knowledge": [], "rules": []},
                {"id": "eng_coder", "name": "Coder", "role": "coder",
                 "identity": "You write code.", "skills": [], "knowledge": [], "rules": []},
            ],
            "skills": [],
        }
        base.update(overrides)
        return base

    def test_valid_passes(self):
        _validate_hr_result(self._valid(), "eng_team")  # no exception

    def test_empty_members_raises(self):
        result = self._valid()
        result["team"]["members"] = []
        with pytest.raises(ValueError, match="no members"):
            _validate_hr_result(result, "eng_team")

    def test_lead_not_in_members_raises(self):
        result = self._valid()
        result["team"]["lead_id"] = "ghost_person"
        with pytest.raises(ValueError, match="lead_id"):
            _validate_hr_result(result, "eng_team")

    def test_invalid_role_raises(self):
        result = self._valid()
        result["persons"][1]["role"] = "developer"
        with pytest.raises(ValueError, match="invalid role"):
            _validate_hr_result(result, "eng_team")

    def test_empty_identity_raises(self):
        result = self._valid()
        result["persons"][0]["identity"] = "   "
        with pytest.raises(ValueError, match="empty identity"):
            _validate_hr_result(result, "eng_team")

    def test_all_valid_roles_accepted(self):
        for role in ("lead", "coder", "reviewer", "tester"):
            result = self._valid()
            result["persons"][0]["role"] = role
            _validate_hr_result(result, "eng_team")  # no exception

    def test_no_persons_is_allowed(self):
        result = self._valid()
        result["persons"] = []
        _validate_hr_result(result, "eng_team")  # no exception — persons list is optional


# ── _create_missing_teams ──────────────────────────────────────────────────────

class TestCreateMissingTeams:
    def _hr_response(self, team_id="new_team"):
        return {
            "team": {
                "id": team_id, "name": "New Team", "skills": [],
                "members": ["nt_lead"], "lead_id": "nt_lead",
                "communication": {"pattern": "lead_delegates", "max_rounds": 3},
            },
            "persons": [
                {"id": "nt_lead", "name": "Lead", "role": "lead",
                 "identity": "You are the lead.", "skills": [], "knowledge": [], "rules": [], "tools": []},
            ],
            "skills": [],
        }

    async def test_skips_existing_team(self, sample_state, sample_team):
        write_state(sample_state)
        statuses = []
        mock_hr = MagicMock()
        with patch("aicompany.planning.HRTeamCreation", mock_hr):
            created = await _create_missing_teams(
                [sample_team.id], ["python"], statuses.append
            )
        mock_hr.assert_not_called()
        assert created == []

    async def test_creates_missing_team(self, sample_state):
        write_state(sample_state)
        hr_instance = MagicMock(run=AsyncMock(return_value=self._hr_response("new_team")))
        with patch("aicompany.planning.HRTeamCreation", return_value=hr_instance):
            created = await _create_missing_teams(["new_team"], ["python"], lambda m: None)
        assert "new_team" in created
        hr_instance.run.assert_called_once()
        loaded = registry.load_team("new_team")
        assert loaded.id == "new_team"
        assert loaded.lead_id == "nt_lead"

    async def test_validation_error_propagates(self, sample_state):
        write_state(sample_state)
        bad_response = {
            "team": {"id": "bad_team", "members": [], "lead_id": "", "skills": []},
            "persons": [],
            "skills": [],
        }
        hr_instance = MagicMock(run=AsyncMock(return_value=bad_response))
        with patch("aicompany.planning.HRTeamCreation", return_value=hr_instance):
            with pytest.raises(ValueError, match="no members"):
                await _create_missing_teams(["bad_team"], [], lambda m: None)

    async def test_saves_persons_and_skills(self, sample_state):
        write_state(sample_state)
        response = self._hr_response("skill_team")
        response["skills"] = [{"id": "golang", "name": "Go", "category": "language", "knowledge": []}]
        hr_instance = MagicMock(run=AsyncMock(return_value=response))
        with patch("aicompany.planning.HRTeamCreation", return_value=hr_instance):
            await _create_missing_teams(["skill_team"], ["go"], lambda m: None)
        person = registry.load_person("nt_lead")
        assert person.role == "lead"
        skill = registry.load_skill("golang")
        assert skill.name == "Go"


# ── _build_task_tree — Issue 1: sub-plan teams created ────────────────────────

class TestBuildTaskTreeTeamCreation:
    """Issue 1: _build_task_tree must call _create_missing_teams for sub-plan teams."""

    def _make_leaf_raw(self, task_id="task_001", team="backend_engineer"):
        return {
            "id": task_id, "title": "Do thing", "description": "Do the thing",
            "assigned_team": team, "depends_on": [], "is_checkpoint": False,
            "requirement_ids": [], "subtasks": [],
        }

    def _make_composite_raw(self, task_id="task_001", sub_team="specialist_team"):
        return {
            "id": task_id, "title": "Big thing",
            "description": "A thing large enough for further decomposition",
            "assigned_team": "", "depends_on": [], "is_checkpoint": False,
            "requirement_ids": [],
            "subtasks": [{"id": "sub_001", "title": "sub"}],
        }

    def _sub_plan_dict(self, team_id="specialist_team"):
        return {
            "title": "Sub Plan",
            "tech_stack": ["python"],
            "teams_required": [team_id],
            "requirements": [],
            "tasks": [
                {"id": "sub_001", "title": "Sub task",
                 "description": "Do the sub thing",
                 "assigned_team": team_id, "depends_on": [], "is_checkpoint": False,
                 "requirement_ids": [], "subtasks": []},
            ],
        }

    async def test_leaf_task_does_not_call_team_creation(self, sample_state, tmp_path):
        write_state(sample_state)
        registry.create_project_dir("proj_test", "reqs")
        proj_dir = registry.project_dir("proj_test")
        mock_create = AsyncMock(return_value=[])
        with patch("aicompany.planning._create_missing_teams", mock_create):
            stubs = await _build_task_tree(
                [self._make_leaf_raw()],
                "proj_test", [], "", proj_dir, lambda m: None,
            )
        mock_create.assert_not_called()
        assert len(stubs) == 1
        assert stubs[0].id == "task_001"

    async def test_composite_task_calls_team_creation_for_sub_plan(
        self, sample_state, tmp_path
    ):
        write_state(sample_state)
        registry.create_project_dir("proj_test", "reqs")
        proj_dir = registry.project_dir("proj_test")

        sub_plan = self._sub_plan_dict("specialist_team")

        def passthrough(artifact, on_status=None):
            return artifact, MagicMock(approved=True)

        mock_create = AsyncMock(return_value=["specialist_team"])
        with patch("aicompany.planning.RequirementsValidation",
                   return_value=MagicMock(run=AsyncMock(side_effect=passthrough))), \
             patch("aicompany.planning.CTOPlanning",
                   return_value=MagicMock(run=AsyncMock(return_value=sub_plan))), \
             patch("aicompany.planning.PlanValidation",
                   return_value=MagicMock(run=AsyncMock(side_effect=passthrough))), \
             patch("aicompany.planning._create_missing_teams", mock_create):
            stubs = await _build_task_tree(
                [self._make_composite_raw()],
                "proj_test", [], "", proj_dir, lambda m: None,
            )

        # _create_missing_teams must have been called with the sub-plan's teams_required
        mock_create.assert_called_once()
        call_args = mock_create.call_args
        assert "specialist_team" in call_args[0][0]  # first positional arg = teams_required

    async def test_composite_task_passes_sub_tech_stack_to_team_creation(
        self, sample_state
    ):
        write_state(sample_state)
        registry.create_project_dir("proj_test", "reqs")
        proj_dir = registry.project_dir("proj_test")

        sub_plan = {**self._sub_plan_dict(), "tech_stack": ["rust", "wasm"]}

        def passthrough(artifact, on_status=None):
            return artifact, MagicMock(approved=True)

        mock_create = AsyncMock(return_value=[])
        with patch("aicompany.planning.RequirementsValidation",
                   return_value=MagicMock(run=AsyncMock(side_effect=passthrough))), \
             patch("aicompany.planning.CTOPlanning",
                   return_value=MagicMock(run=AsyncMock(return_value=sub_plan))), \
             patch("aicompany.planning.PlanValidation",
                   return_value=MagicMock(run=AsyncMock(side_effect=passthrough))), \
             patch("aicompany.planning._create_missing_teams", mock_create):
            await _build_task_tree(
                [self._make_composite_raw()],
                "proj_test", [], "", proj_dir, lambda m: None,
            )

        call_args = mock_create.call_args
        assert call_args[0][1] == ["rust", "wasm"]  # second positional arg = tech_stack

    async def test_no_team_creation_when_sub_plan_teams_required_empty(
        self, sample_state
    ):
        write_state(sample_state)
        registry.create_project_dir("proj_test", "reqs")
        proj_dir = registry.project_dir("proj_test")

        sub_plan = {**self._sub_plan_dict(), "teams_required": []}

        def passthrough(artifact, on_status=None):
            return artifact, MagicMock(approved=True)

        mock_create = AsyncMock(return_value=[])
        with patch("aicompany.planning.RequirementsValidation",
                   return_value=MagicMock(run=AsyncMock(side_effect=passthrough))), \
             patch("aicompany.planning.CTOPlanning",
                   return_value=MagicMock(run=AsyncMock(return_value=sub_plan))), \
             patch("aicompany.planning.PlanValidation",
                   return_value=MagicMock(run=AsyncMock(side_effect=passthrough))), \
             patch("aicompany.planning._create_missing_teams", mock_create):
            await _build_task_tree(
                [self._make_composite_raw()],
                "proj_test", [], "", proj_dir, lambda m: None,
            )

        mock_create.assert_not_called()


# ── CTOPlanning — file output ─────────────────────────────────────────────────

class TestCTOPlanning:
    """CTOPlanning.run() reads the plan from cto_plan.json written by the CTO agent."""

    def _valid_plan(self) -> dict:
        return {
            "title": "Test Project", "tech_stack": ["python"],
            "teams_required": [], "requirements": [], "tasks": [],
        }

    def _mock_cto_team(self):
        lead = Person(id="cto", name="CTO", role="lead", identity="You are CTO.")
        analyst = Person(id="cto_analyst", name="Analyst", role="reviewer", identity="You review.")
        team = Team(id="cto_team", name="CTO Office", skills=[],
                    members=["cto", "cto_analyst"], lead_id="cto")
        return team, lead, [lead, analyst], {}

    def _run_pattern_that_writes(self, plan: dict):
        async def side_effect(**kwargs):
            (config.BASE_DIR / "cto_plan.json").write_text(
                json.dumps(plan), encoding="utf-8"
            )
            return "CTO analysis complete."
        return AsyncMock(side_effect=side_effect)

    async def test_reads_plan_from_file(self, sample_state):
        write_state(sample_state)
        plan = self._valid_plan()
        with patch("aicompany.planning.run_pattern", self._run_pattern_that_writes(plan)), \
             patch("aicompany.planning.registry.load_team_with_members",
                   return_value=self._mock_cto_team()):
            result = await CTOPlanning().run("Build something useful.", lambda m: None)
        assert result["title"] == "Test Project"
        assert result["tech_stack"] == ["python"]

    async def test_file_cleaned_up_after_read(self, sample_state):
        write_state(sample_state)
        plan_file = config.BASE_DIR / "cto_plan.json"
        with patch("aicompany.planning.run_pattern",
                   self._run_pattern_that_writes(self._valid_plan())), \
             patch("aicompany.planning.registry.load_team_with_members",
                   return_value=self._mock_cto_team()):
            await CTOPlanning().run("Build something useful.", lambda m: None)
        assert not plan_file.exists()

    async def test_raises_if_file_missing(self, sample_state):
        write_state(sample_state)
        with patch("aicompany.planning.run_pattern", AsyncMock(return_value="no file written")), \
             patch("aicompany.planning.registry.load_team_with_members",
                   return_value=self._mock_cto_team()):
            with pytest.raises(ValueError, match="cto_plan.json"):
                await CTOPlanning().run("Build something useful.", lambda m: None)

    async def test_leftover_file_removed_before_run(self, sample_state):
        write_state(sample_state)
        plan_file = config.BASE_DIR / "cto_plan.json"
        plan_file.write_text('{"stale": true}', encoding="utf-8")

        seen_at_start: list[bool] = []

        async def write_fresh(**kwargs):
            seen_at_start.append(plan_file.exists())
            plan_file.write_text(json.dumps(self._valid_plan()), encoding="utf-8")
            return "ok"

        with patch("aicompany.planning.run_pattern", AsyncMock(side_effect=write_fresh)), \
             patch("aicompany.planning.registry.load_team_with_members",
                   return_value=self._mock_cto_team()):
            await CTOPlanning().run("Build something useful.", lambda m: None)

        assert seen_at_start == [False], "leftover file should have been deleted before run_pattern"
