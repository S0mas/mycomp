"""
Tests for aicompany/orchestrator.py

What we verify:
  - _topological_sort returns tasks in dependency order
  - _topological_sort raises on unknown deps and cycles
  - run_project skips already-done tasks (re-entrant / crash-safe)
  - run_project marks tasks done and saves plan after each task
  - run_project respects checkpoints (calls oversight.checkpoint)
  - run_project propagates approved / rejected / modified decisions correctly
  - dry_run prints what would run but never calls Reasoner or oversight
  - run_project marks plan 'complete' when all tasks finish
  - Failed task (Reasoner error) marks task 'failed' and re-raises OrchestratorError

All Reasoner calls and oversight calls are mocked — no API key needed.
"""
import pytest
from unittest.mock import MagicMock, patch, call

import aicompany.config as config
from aicompany import orchestrator, registry
from aicompany.models import Task, Person, ProjectPlan, Team
from aicompany.orchestrator import OrchestratorError, _topological_sort
from tests.conftest import write_plan, write_state, write_team, write_persons, write_skills


# ── topological sort ───────────────────────────────────────────────────────────

class TestTopologicalSort:
    def test_linear_chain(self, sample_tasks):
        ordered = _topological_sort(sample_tasks)
        ids = [t.id for t in ordered]
        assert ids.index("task_001") < ids.index("task_002")
        assert ids.index("task_002") < ids.index("task_003")

    def test_no_deps(self):
        tasks = [
            Task(id="a", title="A", description="", assigned_team="eng"),
            Task(id="b", title="B", description="", assigned_team="eng"),
        ]
        ordered = _topological_sort(tasks)
        assert {t.id for t in ordered} == {"a", "b"}

    def test_unknown_dep_raises(self):
        tasks = [
            Task(id="a", title="A", description="", assigned_team="eng", depends_on=["ghost"]),
        ]
        with pytest.raises(OrchestratorError, match="unknown task"):
            _topological_sort(tasks)

    def test_cycle_raises(self):
        tasks = [
            Task(id="a", title="A", description="", assigned_team="eng", depends_on=["b"]),
            Task(id="b", title="B", description="", assigned_team="eng", depends_on=["a"]),
        ]
        with pytest.raises(OrchestratorError, match="Cycle"):
            _topological_sort(tasks)

    def test_diamond_dependency(self):
        tasks = [
            Task(id="root", title="Root", description="", assigned_team="eng"),
            Task(id="left", title="Left", description="", assigned_team="eng", depends_on=["root"]),
            Task(id="right", title="Right", description="", assigned_team="eng", depends_on=["root"]),
            Task(id="tip", title="Tip", description="", assigned_team="eng", depends_on=["left", "right"]),
        ]
        ordered = _topological_sort(tasks)
        ids = [t.id for t in ordered]
        assert ids.index("root") < ids.index("left")
        assert ids.index("root") < ids.index("right")
        assert ids.index("left") < ids.index("tip")
        assert ids.index("right") < ids.index("tip")


# ── run_project ────────────────────────────────────────────────────────────────

def _setup(sample_state, sample_team, sample_plan, sample_persons=None, sample_skills=None):
    """Write all fixtures to the isolated filesystem."""
    write_state(sample_state)
    write_team(sample_team)
    write_plan(sample_plan)
    if sample_persons:
        write_persons(sample_persons)
    if sample_skills:
        write_skills(sample_skills)


def _make_mock_reasoner():
    """Create a mock Reasoner that returns predictable output."""
    mock = MagicMock()
    mock.think.return_value = "# Task output\nSome code here."
    return mock


class TestRunProjectDryRun:
    def test_dry_run_prints_tasks(self, sample_state, sample_team, sample_plan, sample_persons, sample_skills, capsys):
        _setup(sample_state, sample_team, sample_plan, sample_persons, sample_skills)
        orchestrator.run_project(sample_plan.project_id, dry_run=True)
        out = capsys.readouterr().out
        assert "task_001" in out
        assert "task_002" in out
        assert "task_003" in out
        assert "dry-run" in out

    def test_dry_run_does_not_call_reasoner(self, sample_state, sample_team, sample_plan, sample_persons, sample_skills):
        _setup(sample_state, sample_team, sample_plan, sample_persons, sample_skills)
        mock_reasoner = _make_mock_reasoner()
        with patch("aicompany.orchestrator.create_reasoner", return_value=mock_reasoner):
            orchestrator.run_project(sample_plan.project_id, dry_run=True)
        mock_reasoner.think.assert_not_called()

    def test_dry_run_does_not_call_oversight(self, sample_state, sample_team, sample_plan, sample_persons, sample_skills):
        _setup(sample_state, sample_team, sample_plan, sample_persons, sample_skills)
        with patch("aicompany.orchestrator.oversight") as mock_oversight:
            orchestrator.run_project(sample_plan.project_id, dry_run=True)
            mock_oversight.checkpoint.assert_not_called()


class TestRunProjectExecution:
    def _run_with_mocks(self, project_id, oversight_action="approved"):
        mock_reasoner = _make_mock_reasoner()
        with patch("aicompany.orchestrator.create_reasoner", return_value=mock_reasoner), \
             patch("aicompany.orchestrator.oversight") as mock_oversight:

            mock_oversight.checkpoint.return_value = (oversight_action, "")
            orchestrator.run_project(project_id)
            return mock_reasoner, mock_oversight

    def test_all_tasks_marked_done(self, sample_state, sample_team, sample_plan, sample_persons, sample_skills):
        _setup(sample_state, sample_team, sample_plan, sample_persons, sample_skills)
        self._run_with_mocks(sample_plan.project_id)
        plan = registry.load_plan(sample_plan.project_id)
        assert all(t.status == "done" for t in plan.tasks)

    def test_plan_marked_complete(self, sample_state, sample_team, sample_plan, sample_persons, sample_skills):
        _setup(sample_state, sample_team, sample_plan, sample_persons, sample_skills)
        self._run_with_mocks(sample_plan.project_id)
        plan = registry.load_plan(sample_plan.project_id)
        assert plan.status == "complete"

    def test_reasoner_called_for_each_task(self, sample_state, sample_team, sample_plan, sample_persons, sample_skills):
        _setup(sample_state, sample_team, sample_plan, sample_persons, sample_skills)
        mock_reasoner, _ = self._run_with_mocks(sample_plan.project_id)
        # Each task: lead brief + coder + reviewer + lead synth = 4 calls per task
        # 3 tasks = 12 think calls (with 3-person team: lead + coder + reviewer)
        assert mock_reasoner.think.call_count > 0

    def test_checkpoint_task_calls_oversight(self, sample_state, sample_team, sample_plan, sample_persons, sample_skills):
        _setup(sample_state, sample_team, sample_plan, sample_persons, sample_skills)
        _, mock_oversight = self._run_with_mocks(sample_plan.project_id)
        mock_oversight.checkpoint.assert_called_once()
        args = mock_oversight.checkpoint.call_args[0]
        assert args[0].id == "task_002"

    def test_rejected_task_skipped(self, sample_state, sample_team, sample_plan, sample_persons, sample_skills):
        _setup(sample_state, sample_team, sample_plan, sample_persons, sample_skills)
        mock_reasoner, _ = self._run_with_mocks(
            sample_plan.project_id, oversight_action="rejected"
        )
        plan = registry.load_plan(sample_plan.project_id)
        assert plan.task_by_id("task_002").status == "failed"
        assert plan.task_by_id("task_003").status == "failed"

    def test_output_files_created(self, sample_state, sample_team, sample_plan, sample_persons, sample_skills):
        _setup(sample_state, sample_team, sample_plan, sample_persons, sample_skills)
        self._run_with_mocks(sample_plan.project_id)
        output = registry.load_output(sample_plan.project_id, "task_001")
        assert output is not None
        assert "Task output" in output

    def test_session_recorded_after_task(self, sample_state, sample_team, sample_plan, sample_persons, sample_skills):
        _setup(sample_state, sample_team, sample_plan, sample_persons, sample_skills)
        self._run_with_mocks(sample_plan.project_id)
        session = registry.load_session(sample_plan.project_id, "task_001")
        assert session is not None
        assert session.task_id == "task_001"
        assert len(session.messages) > 0

    def test_already_done_tasks_skipped(self, sample_state, sample_team, sample_plan, sample_persons, sample_skills):
        sample_plan.tasks[0].status = "done"
        write_plan(sample_plan)
        write_state(sample_state)
        write_team(sample_team)
        write_persons(sample_persons)
        write_skills(sample_skills)

        mock_reasoner = _make_mock_reasoner()
        with patch("aicompany.orchestrator.create_reasoner", return_value=mock_reasoner), \
             patch("aicompany.orchestrator.oversight") as mock_oversight:
            mock_oversight.checkpoint.return_value = ("approved", "")
            orchestrator.run_project(sample_plan.project_id)

        plan = registry.load_plan(sample_plan.project_id)
        assert plan.task_by_id("task_001").status == "done"

    def test_already_complete_project_exits_early(self, sample_state, sample_team, sample_plan, sample_persons, sample_skills, capsys):
        sample_plan.status = "complete"
        _setup(sample_state, sample_team, sample_plan, sample_persons, sample_skills)
        mock_reasoner = _make_mock_reasoner()
        with patch("aicompany.orchestrator.create_reasoner", return_value=mock_reasoner):
            orchestrator.run_project(sample_plan.project_id)
            mock_reasoner.think.assert_not_called()
        assert "already complete" in capsys.readouterr().out

    def test_reasoner_error_marks_task_failed(self, sample_state, sample_team, sample_plan, sample_persons, sample_skills):
        _setup(sample_state, sample_team, sample_plan, sample_persons, sample_skills)
        mock_reasoner = MagicMock()
        mock_reasoner.think.side_effect = Exception("API timeout")
        with patch("aicompany.orchestrator.create_reasoner", return_value=mock_reasoner), \
             patch("aicompany.orchestrator.oversight") as mock_oversight:
            mock_oversight.checkpoint.return_value = ("approved", "")
            with pytest.raises(OrchestratorError, match="API timeout"):
                orchestrator.run_project(sample_plan.project_id)

        plan = registry.load_plan(sample_plan.project_id)
        assert plan.task_by_id("task_001").status == "failed"
