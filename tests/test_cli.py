"""
Tests for aicompany/cli.py (Click commands)

What we verify:
  - `init` creates state.yaml and seeds cto_team + skills
  - `init` is idempotent (second run warns, doesn't crash)
  - `new-project` reads requirements, runs CTO+HR, saves plan
  - `run` delegates to orchestrator.run_project
  - `run --dry-run` passes dry_run=True
  - `status` without args lists projects
  - `status <id>` shows task breakdown

All agent calls are mocked — no API key needed.
"""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from click.testing import CliRunner

import aicompany.config as config
from aicompany.cli import cli
from aicompany import registry
from aicompany.models import CompanyState, RequirementsEvaluation, Team
from tests.conftest import write_state, write_team, write_plan, write_persons


def _mock_eval(verdict="proceed", summary="Looks good."):
    return AsyncMock(return_value=RequirementsEvaluation(
        clarity=5, completeness=5, feasibility=5,
        verdict=verdict, summary=summary,
    ))


MOCK_CTO_RESPONSE = {
    "title": "Simple REST API",
    "tech_stack": ["python", "fastapi"],
    "teams_required": ["backend_team"],
    "requirements": [],
    "tasks": [{
        "id": "task_001",
        "title": "Design schema",
        "description": "Create DB schema",
        "assigned_team": "backend_team",
        "depends_on": [],
        "is_checkpoint": False,
        "requirement_ids": [],
    }],
}

MOCK_HR_RESPONSE = {
    "team": {
        "id": "backend_team", "name": "Backend Team",
        "skills": [], "members": ["be_lead"], "lead_id": "be_lead",
    },
    "persons": [{
        "id": "be_lead", "name": "BE Lead", "role": "lead",
        "identity": "You are a backend lead.", "skills": [],
        "knowledge": [], "rules": [], "tools": [],
    }],
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

    def test_creates_requirements_policy_file(self, runner):
        runner.invoke(cli, ["init"])
        assert config.REQUIREMENTS_POLICY_FILE.exists()
        content = config.REQUIREMENTS_POLICY_FILE.read_text()
        assert "acceptance criteria" in content.lower()


# ── new-project ────────────────────────────────────────────────────────────────

class TestNewProject:
    def _run_new_project(self, runner, requirements_file,
                         cto_response=None, hr_response=None,
                         eval_verdict="proceed"):
        runner.invoke(cli, ["init"])
        with patch("aicompany.planning._run_cto_planning",
                   new=AsyncMock(return_value=cto_response or MOCK_CTO_RESPONSE)), \
             patch("aicompany.planning._hr_create_team",
                   new=AsyncMock(return_value=hr_response or MOCK_HR_RESPONSE)), \
             patch("aicompany.cli.evaluate_requirements",
                   new=_mock_eval(eval_verdict)):
            result = runner.invoke(cli, ["new-project", requirements_file])
        return result

    def test_exits_zero(self, runner, requirements_file):
        result = self._run_new_project(runner, requirements_file)
        assert result.exit_code == 0, result.output

    def test_plan_file_created(self, runner, requirements_file):
        self._run_new_project(runner, requirements_file)
        projects = registry.list_projects()
        assert len(projects) == 1
        plan = registry.load_plan(projects[0])
        assert plan.title == "Simple REST API"

    def test_tasks_in_plan(self, runner, requirements_file):
        self._run_new_project(runner, requirements_file)
        plan = registry.load_plan(registry.list_projects()[0])
        assert len(plan.tasks) == 1
        assert plan.tasks[0].id == "task_001"

    def test_output_shows_project_id(self, runner, requirements_file):
        result = self._run_new_project(runner, requirements_file)
        assert "proj_" in result.output

    def test_no_hr_call_when_team_exists(self, runner, requirements_file):
        runner.invoke(cli, ["init"])
        mock_hr = AsyncMock(return_value=MOCK_HR_RESPONSE)
        cto_using_seeded = {**MOCK_CTO_RESPONSE, "teams_required": ["cto_team"]}
        with patch("aicompany.planning._run_cto_planning",
                   new=AsyncMock(return_value=cto_using_seeded)), \
             patch("aicompany.planning._hr_create_team", new=mock_hr), \
             patch("aicompany.cli.evaluate_requirements", new=_mock_eval()):
            runner.invoke(cli, ["new-project", requirements_file])
        mock_hr.assert_not_called()

    def test_hr_called_for_missing_team(self, runner, requirements_file):
        runner.invoke(cli, ["init"])
        mock_hr = AsyncMock(return_value=MOCK_HR_RESPONSE)
        with patch("aicompany.planning._run_cto_planning",
                   new=AsyncMock(return_value=MOCK_CTO_RESPONSE)), \
             patch("aicompany.planning._hr_create_team", new=mock_hr), \
             patch("aicompany.cli.evaluate_requirements", new=_mock_eval()):
            runner.invoke(cli, ["new-project", requirements_file])
        mock_hr.assert_called_once()

    def test_requirements_md_copied_into_project(self, runner, requirements_file):
        self._run_new_project(runner, requirements_file)
        proj_id = registry.list_projects()[0]
        req_file = config.PROJECTS_DIR / proj_id / "requirements.md"
        assert req_file.exists()
        assert "REST API" in req_file.read_text()

    def test_cto_called(self, runner, requirements_file):
        runner.invoke(cli, ["init"])
        mock_cto = AsyncMock(return_value=MOCK_CTO_RESPONSE)
        with patch("aicompany.planning._run_cto_planning", new=mock_cto), \
             patch("aicompany.planning._hr_create_team",
                   new=AsyncMock(return_value=MOCK_HR_RESPONSE)), \
             patch("aicompany.cli.evaluate_requirements", new=_mock_eval()):
            runner.invoke(cli, ["new-project", requirements_file])
        mock_cto.assert_called_once()

    def test_evaluation_reject_blocks_planning(self, runner, requirements_file):
        runner.invoke(cli, ["init"])
        mock_cto = AsyncMock(return_value=MOCK_CTO_RESPONSE)
        with patch("aicompany.planning._run_cto_planning", new=mock_cto), \
             patch("aicompany.planning._hr_create_team",
                   new=AsyncMock(return_value=MOCK_HR_RESPONSE)), \
             patch("aicompany.cli.evaluate_requirements",
                   new=_mock_eval("reject", "Too vague.")):
            result = runner.invoke(cli, ["new-project", requirements_file])
        assert result.exit_code == 1
        mock_cto.assert_not_called()

    def test_evaluation_needs_work_warns_but_continues(self, runner, requirements_file):
        result = self._run_new_project(runner, requirements_file, eval_verdict="needs_work")
        assert result.exit_code == 0
        assert "need improvement" in result.output.lower() or "Proceeding anyway" in result.output

    def test_short_requirements_rejected(self, runner, tmp_path):
        short_req = tmp_path / "short.md"
        short_req.write_text("too short")
        runner.invoke(cli, ["init"])
        result = runner.invoke(cli, ["new-project", str(short_req)])
        assert result.exit_code == 1


# ── run ────────────────────────────────────────────────────────────────────────

class TestRun:
    def test_delegates_to_orchestrator(self, runner, sample_state, sample_team,
                                        sample_plan, sample_persons):
        write_state(sample_state)
        write_team(sample_team)
        write_plan(sample_plan)
        write_persons(sample_persons)

        with patch("aicompany.cli.orchestrator") as mock_orch:
            mock_orch.run_project = AsyncMock()
            runner.invoke(cli, ["run", sample_plan.project_id])
            mock_orch.run_project.assert_called_once_with(
                sample_plan.project_id, dry_run=False)

    def test_dry_run_flag(self, runner, sample_state, sample_team,
                          sample_plan, sample_persons):
        write_state(sample_state)
        write_team(sample_team)
        write_plan(sample_plan)
        write_persons(sample_persons)

        with patch("aicompany.cli.orchestrator") as mock_orch:
            mock_orch.run_project = AsyncMock()
            runner.invoke(cli, ["run", "--dry-run", sample_plan.project_id])
            mock_orch.run_project.assert_called_once_with(
                sample_plan.project_id, dry_run=True)

    def test_orchestrator_error_exits_nonzero(self, runner, sample_state,
                                               sample_team, sample_plan, sample_persons):
        write_state(sample_state)
        write_team(sample_team)
        write_plan(sample_plan)
        write_persons(sample_persons)

        from aicompany.orchestrator import OrchestratorError

        async def _raise(*a, **kw):
            raise OrchestratorError("boom")

        with patch("aicompany.cli.orchestrator") as mock_orch:
            mock_orch.run_project = _raise
            mock_orch.OrchestratorError = OrchestratorError
            result = runner.invoke(cli, ["run", sample_plan.project_id])
        assert result.exit_code == 1


# ── retry ──────────────────────────────────────────────────────────────────────

class TestRetry:
    def test_resets_failed_tasks_and_reruns(self, runner, sample_state,
                                             sample_team, sample_plan, sample_persons):
        sample_plan.tasks[1].status = "failed"
        sample_plan.tasks[2].status = "failed"
        write_state(sample_state)
        write_team(sample_team)
        write_plan(sample_plan)
        write_persons(sample_persons)

        with patch("aicompany.cli.orchestrator") as mock_orch:
            mock_orch.run_project = AsyncMock()
            runner.invoke(cli, ["retry", sample_plan.project_id])
            mock_orch.run_project.assert_called_once()

        plan = registry.load_plan(sample_plan.project_id)
        assert plan.tasks[1].status == "pending"
        assert plan.tasks[2].status == "pending"

    def test_nothing_to_retry_when_no_failures(self, runner, sample_plan):
        write_plan(sample_plan)
        result = runner.invoke(cli, ["retry", sample_plan.project_id])
        assert result.exit_code == 0
        assert "nothing to retry" in result.output.lower()

    def test_unknown_project_exits_nonzero(self, runner):
        result = runner.invoke(cli, ["retry", "proj_doesnotexist"])
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
            {"task_id": "task_002", "action": "approved",
             "timestamp": "2026-01-01T10:00:00+00:00"},
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
