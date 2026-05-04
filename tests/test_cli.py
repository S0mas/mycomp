"""
Tests for aicompany/cli.py  (Click commands)

What we verify:
  - `init` creates state.yaml and seeds two teams
  - `init` is idempotent (second run warns, doesn't crash)
  - `new-project` reads requirements, calls CTO + HR, saves plan
  - `new-project` creates missing teams via HR agent
  - `new-project` reuses existing teams (no HR call when skill already present)
  - `run` delegates to orchestrator.run_project
  - `run --dry-run` passes dry_run=True
  - `status` without args lists projects
  - `status <id>` shows task breakdown

All LLM calls are mocked — no API key needed.
"""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from click.testing import CliRunner

import aicompany.config as config
from aicompany.cli import cli
from aicompany import registry
from aicompany.models import CompanyState, Team
from tests.conftest import write_state, write_team, write_plan, write_persons


MOCK_PLAN_RESPONSE = {
    "title": "Simple REST API",
    "tech_stack": ["python", "fastapi"],
    "teams_required": ["backend_team"],
    "tasks": [
        {
            "id": "task_001",
            "title": "Design schema",
            "description": "Create DB schema",
            "assigned_team": "backend_team",
            "depends_on": [],
            "is_checkpoint": False,
        }
    ],
}

MOCK_TEAM_RESPONSE = {
    "team": {
        "id": "devops_team",
        "name": "DevOps Team",
        "skills": ["docker", "kubernetes", "terraform"],
        "members": ["devops_lead", "devops_coder"],
        "lead_id": "devops_lead",
    },
    "persons": [
        {
            "id": "devops_lead",
            "name": "DevOps Lead",
            "role": "lead",
            "identity": "You are a DevOps lead.",
            "skills": ["docker", "kubernetes"],
            "knowledge": [],
            "rules": ["Coordinate deployments"],
            "tools": [],
        },
        {
            "id": "devops_coder",
            "name": "DevOps Engineer",
            "role": "coder",
            "identity": "You are a DevOps engineer.",
            "skills": ["docker", "kubernetes", "terraform"],
            "knowledge": [],
            "rules": ["Write infrastructure as code"],
            "tools": [],
        },
    ],
    "skills": [],
}


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def requirements_file(tmp_path):
    f = tmp_path / "requirements.md"
    f.write_text("# Build a simple REST API\nNeeds CRUD endpoints for users.")
    return str(f)


# ── init ───────────────────────────────────────────────────────────────────────

class TestInit:
    def test_creates_state_file(self, runner):
        result = runner.invoke(cli, ["init"])
        assert result.exit_code == 0
        assert config.STATE_FILE.exists()

    def test_seeds_two_teams(self, runner):
        runner.invoke(cli, ["init"])
        state = registry.load_state()
        assert "backend_team" in state.team_ids()
        assert "frontend_team" in state.team_ids()

    def test_team_yaml_files_created(self, runner):
        runner.invoke(cli, ["init"])
        assert (config.TEAMS_DIR / "backend_team.yaml").exists()
        assert (config.TEAMS_DIR / "frontend_team.yaml").exists()

    def test_idempotent_second_run_warns(self, runner):
        runner.invoke(cli, ["init"])
        result = runner.invoke(cli, ["init"])
        assert result.exit_code == 0
        assert "already initialised" in result.output


# ── new-project ────────────────────────────────────────────────────────────────

MOCK_EVAL_RESPONSE = {
    "clarity": 4, "completeness": 4, "feasibility": 5,
    "risks": [], "suggestions": [], "summary": "Looks good.", "verdict": "proceed",
}


class TestNewProject:
    def _run_new_project(self, runner, requirements_file, cto_response=None, hr_response=None):
        cto_resp = cto_response or MOCK_PLAN_RESPONSE
        runner.invoke(cli, ["init"])

        with patch("aicompany.cli.llm") as mock_llm:
            mock_llm.cto_analyze.return_value = cto_resp
            mock_llm.hr_create_team.return_value = hr_response or MOCK_TEAM_RESPONSE
            mock_llm.evaluate_requirements.return_value = MOCK_EVAL_RESPONSE
            result = runner.invoke(cli, ["new-project", requirements_file])
        return result, mock_llm

    def test_exits_zero(self, runner, requirements_file):
        result, _ = self._run_new_project(runner, requirements_file)
        assert result.exit_code == 0, result.output

    def test_calls_cto_analyze(self, runner, requirements_file):
        _, mock_llm = self._run_new_project(runner, requirements_file)
        mock_llm.cto_analyze.assert_called_once()

    def test_plan_file_created(self, runner, requirements_file):
        result, _ = self._run_new_project(runner, requirements_file)
        projects = registry.list_projects()
        assert len(projects) == 1
        plan = registry.load_plan(projects[0])
        assert plan.title == "Simple REST API"

    def test_tasks_in_plan(self, runner, requirements_file):
        self._run_new_project(runner, requirements_file)
        plan = registry.load_plan(registry.list_projects()[0])
        assert len(plan.tasks) == 1
        assert plan.tasks[0].id == "task_001"

    def test_no_hr_call_when_team_exists(self, runner, requirements_file):
        """backend_team is seeded by init — HR should not be called."""
        _, mock_llm = self._run_new_project(runner, requirements_file)
        mock_llm.hr_create_team.assert_not_called()

    def test_hr_called_for_missing_team(self, runner, requirements_file):
        plan_needing_devops = {
            **MOCK_PLAN_RESPONSE,
            "teams_required": ["backend_team", "devops_team"],
            "tasks": MOCK_PLAN_RESPONSE["tasks"] + [{
                "id": "task_002",
                "title": "Deploy",
                "description": "Deploy to prod",
                "assigned_team": "devops_team",
                "depends_on": ["task_001"],
                "is_checkpoint": True,
            }],
        }
        _, mock_llm = self._run_new_project(runner, requirements_file, cto_response=plan_needing_devops)
        mock_llm.hr_create_team.assert_called_once()
        call_args = mock_llm.hr_create_team.call_args[0]
        assert call_args[0] == "devops_team"

    def test_requirements_md_copied_into_project(self, runner, requirements_file):
        self._run_new_project(runner, requirements_file)
        proj_id = registry.list_projects()[0]
        req_file = config.PROJECTS_DIR / proj_id / "requirements.md"
        assert req_file.exists()
        assert "REST API" in req_file.read_text()

    def test_output_shows_project_id(self, runner, requirements_file):
        result, _ = self._run_new_project(runner, requirements_file)
        assert "proj_" in result.output

    def test_hard_block_on_low_overall_score(self, runner, requirements_file):
        low_eval = {**MOCK_EVAL_RESPONSE, "clarity": 1, "completeness": 1, "feasibility": 1, "verdict": "reject"}
        runner.invoke(cli, ["init"])
        with patch("aicompany.cli.llm") as mock_llm:
            mock_llm.evaluate_requirements.return_value = low_eval
            result = runner.invoke(cli, ["new-project", requirements_file], input="n\n")
        assert result.exit_code == 1
        assert "Cannot proceed" in result.output

    def test_hard_block_on_single_low_dimension(self, runner, requirements_file):
        low_eval = {**MOCK_EVAL_RESPONSE, "clarity": 2}
        runner.invoke(cli, ["init"])
        with patch("aicompany.cli.llm") as mock_llm:
            mock_llm.evaluate_requirements.return_value = low_eval
            result = runner.invoke(cli, ["new-project", requirements_file], input="n\n")
        assert result.exit_code == 1
        assert "Clarity" in result.output

    def test_hard_block_on_reject_verdict(self, runner, requirements_file):
        reject_eval = {**MOCK_EVAL_RESPONSE, "verdict": "reject"}
        runner.invoke(cli, ["init"])
        with patch("aicompany.cli.llm") as mock_llm:
            mock_llm.evaluate_requirements.return_value = reject_eval
            result = runner.invoke(cli, ["new-project", requirements_file], input="n\n")
        assert result.exit_code == 1
        assert "REJECT" in result.output

    def test_autofix_saves_fixed_file(self, runner, requirements_file):
        low_eval = {**MOCK_EVAL_RESPONSE, "clarity": 2, "verdict": "needs_work"}
        runner.invoke(cli, ["init"])
        with patch("aicompany.cli.llm") as mock_llm:
            mock_llm.evaluate_requirements.return_value = low_eval
            mock_llm.autofix_requirements.return_value = "# Improved Requirements\n\nBuild a REST API."
            result = runner.invoke(cli, ["new-project", requirements_file], input="y\n")
        assert result.exit_code == 1
        assert "Improved requirements saved" in result.output
        mock_llm.autofix_requirements.assert_called_once()


# ── run ────────────────────────────────────────────────────────────────────────

class TestRun:
    def test_delegates_to_orchestrator(self, runner, sample_state, sample_team, sample_plan, sample_persons):
        write_state(sample_state)
        write_team(sample_team)
        write_plan(sample_plan)
        write_persons(sample_persons)

        with patch("aicompany.cli.orchestrator") as mock_orch:
            result = runner.invoke(cli, ["run", sample_plan.project_id])
            mock_orch.run_project.assert_called_once_with(sample_plan.project_id, dry_run=False)

    def test_dry_run_flag(self, runner, sample_state, sample_team, sample_plan, sample_persons):
        write_state(sample_state)
        write_team(sample_team)
        write_plan(sample_plan)
        write_persons(sample_persons)

        with patch("aicompany.cli.orchestrator") as mock_orch:
            runner.invoke(cli, ["run", "--dry-run", sample_plan.project_id])
            mock_orch.run_project.assert_called_once_with(sample_plan.project_id, dry_run=True)

    def test_orchestrator_error_exits_nonzero(self, runner, sample_state, sample_team, sample_plan, sample_persons):
        write_state(sample_state)
        write_team(sample_team)
        write_plan(sample_plan)
        write_persons(sample_persons)

        from aicompany.orchestrator import OrchestratorError
        with patch("aicompany.cli.orchestrator") as mock_orch:
            mock_orch.run_project.side_effect = OrchestratorError("boom")
            mock_orch.OrchestratorError = OrchestratorError
            result = runner.invoke(cli, ["run", sample_plan.project_id])
            assert result.exit_code == 1


# ── status ─────────────────────────────────────────────────────────────────────

class TestStatus:
    def test_no_projects(self, runner):
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "No projects" in result.output

    def test_lists_projects(self, runner, sample_plan):
        write_plan(sample_plan)
        result = runner.invoke(cli, ["status"])
        assert sample_plan.project_id in result.output

    def test_shows_task_breakdown(self, runner, sample_plan):
        write_plan(sample_plan)
        result = runner.invoke(cli, ["status", sample_plan.project_id])
        assert result.exit_code == 0
        assert "task_001" in result.output
        assert "task_002" in result.output
        assert "CHECKPOINT" in result.output

    def test_shows_plan_status(self, runner, sample_plan):
        write_plan(sample_plan)
        result = runner.invoke(cli, ["status", sample_plan.project_id])
        assert "pending" in result.output
