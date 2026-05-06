"""
Tests for aicompany/cli.py  (Click commands)

What we verify:
  - `init` creates state.yaml and seeds cto_team + skills
  - `init` is idempotent (second run warns, doesn't crash)
  - `new-project` reads requirements, runs CTO team, calls HR, saves plan
  - `new-project` creates missing teams via HR agent
  - `new-project` reuses existing teams (no HR call when team already present)
  - `run` delegates to orchestrator.run_project
  - `run --dry-run` passes dry_run=True
  - `status` without args lists projects
  - `status <id>` shows task breakdown

All LLM/agent calls are mocked — no API key needed.
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
    "requirements": [],
    "tasks": [
        {
            "id": "task_001",
            "title": "Design schema",
            "description": "Create DB schema",
            "assigned_team": "backend_team",
            "depends_on": [],
            "is_checkpoint": False,
            "requirement_ids": [],
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

    def test_seeds_cto_team(self, runner):
        runner.invoke(cli, ["init"])
        state = registry.load_state()
        assert "cto_team" in state.team_ids()

    def test_team_yaml_file_created(self, runner):
        runner.invoke(cli, ["init"])
        assert (config.TEAMS_DIR / "cto_team.yaml").exists()

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
        """
        Helper: run `init` then `new-project`, mocking CTO team planning and LLM calls.

        evaluate_and_gate lives in evaluation.py; plan_and_create_project in planning.py.
        Each module has its own llm import, so we patch both.
        """
        cto_resp = cto_response or MOCK_PLAN_RESPONSE
        runner.invoke(cli, ["init"])

        with patch("aicompany.planning._run_cto_planning", return_value=cto_resp), \
             patch("aicompany.evaluation.llm") as mock_eval_llm, \
             patch("aicompany.planning.llm") as mock_plan_llm:
            mock_eval_llm.evaluate_requirements.return_value = MOCK_EVAL_RESPONSE
            mock_plan_llm.hr_create_team.return_value = hr_response or MOCK_TEAM_RESPONSE
            result = runner.invoke(cli, ["new-project", requirements_file])
        return result, mock_plan_llm

    def test_exits_zero(self, runner, requirements_file):
        result, _ = self._run_new_project(runner, requirements_file)
        assert result.exit_code == 0, result.output

    def test_cto_planning_runs(self, runner, requirements_file):
        with patch("aicompany.planning._run_cto_planning", return_value=MOCK_PLAN_RESPONSE) as mock_cto, \
             patch("aicompany.evaluation.llm") as mock_eval_llm, \
             patch("aicompany.planning.llm") as mock_plan_llm:
            mock_eval_llm.evaluate_requirements.return_value = MOCK_EVAL_RESPONSE
            mock_plan_llm.hr_create_team.return_value = MOCK_TEAM_RESPONSE
            runner.invoke(cli, ["init"])
            runner.invoke(cli, ["new-project", requirements_file])
        mock_cto.assert_called_once()

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
        """cto_team is seeded by init — if CTO requests it, HR should not be called."""
        cto_using_seeded = {**MOCK_PLAN_RESPONSE, "teams_required": ["cto_team"]}
        _, mock_llm = self._run_new_project(runner, requirements_file, cto_response=cto_using_seeded)
        mock_llm.hr_create_team.assert_not_called()

    def test_hr_called_for_missing_team(self, runner, requirements_file):
        plan_needing_devops = {
            **MOCK_PLAN_RESPONSE,
            "teams_required": ["cto_team", "devops_team"],
            "tasks": MOCK_PLAN_RESPONSE["tasks"] + [{
                "id": "task_002",
                "title": "Deploy",
                "description": "Deploy to prod",
                "assigned_team": "devops_team",
                "depends_on": ["task_001"],
                "is_checkpoint": True,
                "requirement_ids": [],
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
        with patch("aicompany.evaluation.llm") as mock_llm:
            mock_llm.evaluate_requirements.return_value = low_eval
            result = runner.invoke(cli, ["new-project", requirements_file], input="n\n")
        assert result.exit_code == 1
        assert "Cannot proceed" in result.output

    def test_hard_block_on_single_low_dimension(self, runner, requirements_file):
        low_eval = {**MOCK_EVAL_RESPONSE, "clarity": 2}
        runner.invoke(cli, ["init"])
        with patch("aicompany.evaluation.llm") as mock_llm:
            mock_llm.evaluate_requirements.return_value = low_eval
            result = runner.invoke(cli, ["new-project", requirements_file], input="n\n")
        assert result.exit_code == 1
        assert "Clarity" in result.output

    def test_hard_block_on_reject_verdict(self, runner, requirements_file):
        reject_eval = {**MOCK_EVAL_RESPONSE, "verdict": "reject"}
        runner.invoke(cli, ["init"])
        with patch("aicompany.evaluation.llm") as mock_llm:
            mock_llm.evaluate_requirements.return_value = reject_eval
            result = runner.invoke(cli, ["new-project", requirements_file], input="n\n")
        assert result.exit_code == 1
        assert "REJECT" in result.output

    def test_autofix_saves_fixed_file(self, runner, requirements_file):
        low_eval = {**MOCK_EVAL_RESPONSE, "clarity": 2, "verdict": "needs_work"}
        runner.invoke(cli, ["init"])
        with patch("aicompany.evaluation.llm") as mock_llm:
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

        with patch("aicompany.cli.orchestrator") as mock_orch, \
             patch.object(config, "MCP_SERVERS", [{"type": "url", "url": "http://fake", "name": "t"}]):
            result = runner.invoke(cli, ["run", sample_plan.project_id])
            mock_orch.run_project.assert_called_once_with(sample_plan.project_id, dry_run=False)

    def test_run_exits_early_without_mcp(self, runner, sample_state, sample_team, sample_plan, sample_persons):
        write_state(sample_state)
        write_team(sample_team)
        write_plan(sample_plan)
        write_persons(sample_persons)

        with patch.object(config, "MCP_SERVERS", []):
            result = runner.invoke(cli, ["run", sample_plan.project_id])
        assert result.exit_code == 1
        assert "AICOMPANY_MCP_SERVERS" in result.output

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
        with patch("aicompany.cli.orchestrator") as mock_orch, \
             patch.object(config, "MCP_SERVERS", [{"type": "url", "url": "http://fake", "name": "t"}]):
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

    def test_shows_decisions_log(self, runner, sample_plan):
        sample_plan.decisions_log = [
            {"task_id": "task_002", "action": "approved", "timestamp": "2026-01-01T10:00:00+00:00"},
        ]
        write_plan(sample_plan)
        result = runner.invoke(cli, ["status", sample_plan.project_id])
        assert result.exit_code == 0
        assert "task_002" in result.output
        assert "APPROVED" in result.output

    def test_no_decisions_section_when_empty(self, runner, sample_plan):
        write_plan(sample_plan)
        result = runner.invoke(cli, ["status", sample_plan.project_id])
        assert "Checkpoint decisions" not in result.output


# ── purge ───────────────────────────────────────────────────────────────────────

class TestPurge:
    def test_purge_removes_company_and_projects(self, runner, sample_state, sample_plan):
        write_state(sample_state)
        write_plan(sample_plan)
        assert config.COMPANY_DIR.exists()
        assert config.PROJECTS_DIR.exists()

        result = runner.invoke(cli, ["purge"], input="y\n")
        assert result.exit_code == 0
        assert not config.COMPANY_DIR.exists()
        assert not config.PROJECTS_DIR.exists()

    def test_purge_clean_state_reports_nothing_to_remove(self, runner):
        # Remove dirs that isolated_fs creates so we hit the "already clean" path
        import shutil
        shutil.rmtree(config.COMPANY_DIR, ignore_errors=True)
        shutil.rmtree(config.PROJECTS_DIR, ignore_errors=True)
        result = runner.invoke(cli, ["purge"], input="y\n")
        assert result.exit_code == 0
        assert "Nothing to remove" in result.output

    def test_purge_aborted_by_user_leaves_state_intact(self, runner, sample_state):
        write_state(sample_state)
        result = runner.invoke(cli, ["purge"], input="n\n")
        assert result.exit_code != 0
        assert config.COMPANY_DIR.exists()

    def test_purge_all_also_removes_venv(self, runner):
        venv = config.BASE_DIR / ".venv"
        venv.mkdir(parents=True, exist_ok=True)
        result = runner.invoke(cli, ["purge", "--all"], input="y\n")
        assert result.exit_code == 0
        assert not venv.exists()

    def test_shows_plan_status(self, runner, sample_plan):
        write_plan(sample_plan)
        result = runner.invoke(cli, ["status", sample_plan.project_id])
        assert "pending" in result.output
