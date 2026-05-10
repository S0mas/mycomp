"""
Tests for aicompany/cli.py (Click commands)

What we verify:
  - `init` creates state.yaml and seeds cto_team + skills + policy files
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
from unittest.mock import AsyncMock, MagicMock, patch
from click.testing import CliRunner


def _make_val_mock():
    """Return a mock ValidationProcess instance whose run() passes the artifact through."""
    def _passthrough(artifact, on_status=None):
        return artifact, MagicMock(approved=True, rejected=False)
    return MagicMock(run=AsyncMock(side_effect=_passthrough))

import aicompany.config as config
from aicompany.cli import cli
from aicompany import registry
from aicompany.models import CompanyState, Team
from tests.conftest import write_state, write_team, write_plan, write_persons


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

def _seed_defaults_to_disk():
    """Write default company files to the (isolated) dirs, simulating a fresh clone."""
    import yaml as _yaml
    from aicompany.seeds import default_skills, default_teams, default_requirements_policy, default_plan_policy

    config.SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    for skill in default_skills():
        with (config.SKILLS_DIR / f"{skill.id}.yaml").open("w") as f:
            _yaml.dump(skill.to_dict(), f, default_flow_style=False)

    persons_dir = config.COMPANY_DIR / "persons"
    persons_dir.mkdir(parents=True, exist_ok=True)
    config.TEAMS_DIR.mkdir(parents=True, exist_ok=True)
    for persons, team in default_teams():
        for person in persons:
            with (persons_dir / f"{person.id}.yaml").open("w") as f:
                _yaml.dump(person.to_dict(), f, default_flow_style=False)
        with (config.TEAMS_DIR / f"{team.id}.yaml").open("w") as f:
            _yaml.dump(team.to_dict(), f, default_flow_style=False)

    config.REQUIREMENTS_POLICY_FILE.write_text(default_requirements_policy(), encoding="utf-8")
    config.PLAN_POLICY_FILE.write_text(default_plan_policy(), encoding="utf-8")


class TestInit:
    def test_creates_state_file(self, runner):
        result = runner.invoke(cli, ["init"])
        assert result.exit_code == 0
        assert config.STATE_FILE.exists()

    def test_indexes_skills_from_disk(self, runner):
        _seed_defaults_to_disk()
        runner.invoke(cli, ["init"])
        state = registry.load_state()
        assert len(state.skills) > 0

    def test_indexes_cto_team_from_disk(self, runner):
        _seed_defaults_to_disk()
        runner.invoke(cli, ["init"])
        state = registry.load_state()
        assert "cto_team" in state.team_ids()

    def test_indexes_cto_persons_from_disk(self, runner):
        _seed_defaults_to_disk()
        runner.invoke(cli, ["init"])
        state = registry.load_state()
        assert "cto" in state.person_ids()

    def test_idempotent_second_run_warns(self, runner):
        runner.invoke(cli, ["init"])
        result = runner.invoke(cli, ["init"])
        assert result.exit_code == 0
        assert "already initialised" in result.output

    def test_empty_dirs_produce_empty_state(self, runner):
        result = runner.invoke(cli, ["init"])
        assert result.exit_code == 0
        state = registry.load_state()
        assert state.skills == []
        assert state.teams == []


# ── new-project ────────────────────────────────────────────────────────────────

def _make_cto_mock(response=None):
    return MagicMock(run=AsyncMock(return_value=response or MOCK_CTO_RESPONSE))


def _make_hr_mock(response=None):
    return MagicMock(run=AsyncMock(return_value=response or MOCK_HR_RESPONSE))


class TestNewProject:
    def _run_new_project(self, runner, requirements_file,
                         cto_response=None, hr_response=None):
        runner.invoke(cli, ["init"])
        with patch("aicompany.planning.CTOPlanning", return_value=_make_cto_mock(cto_response)), \
             patch("aicompany.planning.HRTeamCreation", return_value=_make_hr_mock(hr_response)), \
             patch("aicompany.planning.RequirementsValidation", return_value=_make_val_mock()), \
             patch("aicompany.planning.PlanValidation", return_value=_make_val_mock()), \
             patch("aicompany.planning.Deduplication", return_value=MagicMock(run=AsyncMock())):
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
        _seed_defaults_to_disk()
        runner.invoke(cli, ["init"])
        mock_hr_cls = MagicMock()
        cto_using_seeded = {**MOCK_CTO_RESPONSE, "teams_required": ["cto_team"]}
        with patch("aicompany.planning.CTOPlanning", return_value=_make_cto_mock(cto_using_seeded)), \
             patch("aicompany.planning.HRTeamCreation", mock_hr_cls), \
             patch("aicompany.planning.RequirementsValidation", return_value=_make_val_mock()), \
             patch("aicompany.planning.PlanValidation", return_value=_make_val_mock()), \
             patch("aicompany.planning.Deduplication", return_value=MagicMock(run=AsyncMock())):
            runner.invoke(cli, ["new-project", requirements_file])
        mock_hr_cls.assert_not_called()

    def test_hr_called_for_missing_team(self, runner, requirements_file):
        runner.invoke(cli, ["init"])
        mock_hr_instance = _make_hr_mock()
        mock_hr_cls = MagicMock(return_value=mock_hr_instance)
        with patch("aicompany.planning.CTOPlanning", return_value=_make_cto_mock()), \
             patch("aicompany.planning.HRTeamCreation", mock_hr_cls), \
             patch("aicompany.planning.RequirementsValidation", return_value=_make_val_mock()), \
             patch("aicompany.planning.PlanValidation", return_value=_make_val_mock()), \
             patch("aicompany.planning.Deduplication", return_value=MagicMock(run=AsyncMock())):
            runner.invoke(cli, ["new-project", requirements_file])
        mock_hr_instance.run.assert_called_once()

    def test_requirements_md_copied_into_project(self, runner, requirements_file):
        self._run_new_project(runner, requirements_file)
        proj_id = registry.list_projects()[0]
        req_file = config.PROJECTS_DIR / proj_id / "requirements.md"
        assert req_file.exists()
        assert "REST API" in req_file.read_text()

    def test_cto_called(self, runner, requirements_file):
        runner.invoke(cli, ["init"])
        mock_cto_instance = _make_cto_mock()
        mock_cto_cls = MagicMock(return_value=mock_cto_instance)
        with patch("aicompany.planning.CTOPlanning", mock_cto_cls), \
             patch("aicompany.planning.HRTeamCreation", return_value=_make_hr_mock()), \
             patch("aicompany.planning.RequirementsValidation", return_value=_make_val_mock()), \
             patch("aicompany.planning.PlanValidation", return_value=_make_val_mock()), \
             patch("aicompany.planning.Deduplication", return_value=MagicMock(run=AsyncMock())):
            runner.invoke(cli, ["new-project", requirements_file])
        mock_cto_instance.run.assert_called_once()

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
            runner.invoke(cli, ["run", sample_plan.id])
            mock_orch.run_project.assert_called_once_with(
                sample_plan.id, dry_run=False)

    def test_dry_run_flag(self, runner, sample_state, sample_team,
                          sample_plan, sample_persons):
        write_state(sample_state)
        write_team(sample_team)
        write_plan(sample_plan)
        write_persons(sample_persons)

        with patch("aicompany.cli.orchestrator") as mock_orch:
            mock_orch.run_project = AsyncMock()
            runner.invoke(cli, ["run", "--dry-run", sample_plan.id])
            mock_orch.run_project.assert_called_once_with(
                sample_plan.id, dry_run=True)

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
            result = runner.invoke(cli, ["run", sample_plan.id])
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
            runner.invoke(cli, ["retry", sample_plan.id])
            mock_orch.run_project.assert_called_once()

        plan = registry.load_plan(sample_plan.id)
        assert plan.tasks[1].status == "pending"
        assert plan.tasks[2].status == "pending"

    def test_nothing_to_retry_when_no_failures(self, runner, sample_plan):
        write_plan(sample_plan)
        result = runner.invoke(cli, ["retry", sample_plan.id])
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
        assert sample_plan.id in result.output

    def test_shows_task_breakdown(self, runner, sample_plan):
        write_plan(sample_plan)
        result = runner.invoke(cli, ["status", sample_plan.id])
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
        result = runner.invoke(cli, ["status", sample_plan.id])
        assert result.exit_code == 0
        assert "task_002" in result.output
        assert "APPROVED" in result.output

    def test_no_decisions_section_when_empty(self, runner, sample_plan):
        write_plan(sample_plan)
        result = runner.invoke(cli, ["status", sample_plan.id])
        assert "Checkpoint decisions" not in result.output


# ── purge ───────────────────────────────────────────────────────────────────────

class TestPurge:
    def test_purge_removes_state_and_projects(self, runner, sample_state, sample_plan):
        write_state(sample_state)
        write_plan(sample_plan)
        assert config.STATE_FILE.exists()
        assert config.PROJECTS_DIR.exists()
        result = runner.invoke(cli, ["purge"], input="y\n")
        assert result.exit_code == 0
        assert not config.STATE_FILE.exists()
        assert not config.PROJECTS_DIR.exists()
        assert config.COMPANY_DIR.exists()  # committed defaults preserved

    def test_purge_clean_state_reports_nothing_to_remove(self, runner):
        import shutil
        config.STATE_FILE.unlink(missing_ok=True)
        shutil.rmtree(config.PROJECTS_DIR, ignore_errors=True)
        result = runner.invoke(cli, ["purge"], input="y\n")
        assert result.exit_code == 0
        assert "Nothing to remove" in result.output

    def test_purge_aborted_by_user_leaves_state_intact(self, runner, sample_state):
        write_state(sample_state)
        result = runner.invoke(cli, ["purge"], input="n\n")
        assert result.exit_code != 0
        assert config.STATE_FILE.exists()

    def test_purge_all_also_removes_venv(self, runner):
        venv = config.BASE_DIR / ".venv"
        venv.mkdir(parents=True, exist_ok=True)
        result = runner.invoke(cli, ["purge", "--all"], input="y\n")
        assert result.exit_code == 0
        assert not venv.exists()

    def test_shows_plan_status(self, runner, sample_plan):
        write_plan(sample_plan)
        result = runner.invoke(cli, ["status", sample_plan.id])
        assert "pending" in result.output
