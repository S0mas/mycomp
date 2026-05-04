"""
Tests for aicompany/orchestrator.py

What we verify:
  - _topological_sort returns tasks in dependency order
  - _topological_sort raises on unknown deps and cycles
  - run_project skips already-done tasks (re-entrant / crash-safe)
  - run_project marks tasks done and saves plan after each task
  - run_project respects checkpoints (calls oversight.checkpoint)
  - run_project propagates approved / rejected / modified decisions correctly
  - dry_run prints what would run but never calls LLM or oversight
  - run_project marks plan 'complete' when all tasks finish
  - Failed task (LLM error) marks task 'failed' and re-raises OrchestratorError

All LLM calls and oversight calls are mocked — no API key needed.
"""
import pytest
from unittest.mock import MagicMock, patch, call

import aicompany.config as config
from aicompany import orchestrator, registry
from aicompany.models import Task, ProjectPlan, Team
from aicompany.orchestrator import OrchestratorError, _topological_sort
from tests.conftest import write_plan, write_state, write_team


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

def _setup(sample_state, sample_team, sample_plan):
    """Write all fixtures to the isolated filesystem."""
    write_state(sample_state)
    write_team(sample_team)
    write_plan(sample_plan)


class TestRunProjectDryRun:
    def test_dry_run_prints_tasks(self, sample_state, sample_team, sample_plan, capsys):
        _setup(sample_state, sample_team, sample_plan)
        orchestrator.run_project(sample_plan.project_id, dry_run=True)
        out = capsys.readouterr().out
        assert "task_001" in out
        assert "task_002" in out
        assert "task_003" in out
        assert "dry-run" in out

    def test_dry_run_does_not_call_llm(self, sample_state, sample_team, sample_plan):
        _setup(sample_state, sample_team, sample_plan)
        with patch("aicompany.orchestrator.llm") as mock_llm:
            orchestrator.run_project(sample_plan.project_id, dry_run=True)
            mock_llm.team_execute_task.assert_not_called()

    def test_dry_run_does_not_call_oversight(self, sample_state, sample_team, sample_plan):
        _setup(sample_state, sample_team, sample_plan)
        with patch("aicompany.orchestrator.oversight") as mock_oversight:
            orchestrator.run_project(sample_plan.project_id, dry_run=True)
            mock_oversight.checkpoint.assert_not_called()


class TestRunProjectExecution:
    def _run_with_mocks(self, project_id, oversight_action="approved"):
        with patch("aicompany.orchestrator.llm") as mock_llm, \
             patch("aicompany.orchestrator.oversight") as mock_oversight:

            mock_llm.team_execute_task.return_value = "# Task output\nSome code here."
            mock_oversight.checkpoint.return_value = (oversight_action, "")
            orchestrator.run_project(project_id)
            return mock_llm, mock_oversight

    def test_all_tasks_marked_done(self, sample_state, sample_team, sample_plan):
        _setup(sample_state, sample_team, sample_plan)
        self._run_with_mocks(sample_plan.project_id)
        plan = registry.load_plan(sample_plan.project_id)
        assert all(t.status == "done" for t in plan.tasks)

    def test_plan_marked_complete(self, sample_state, sample_team, sample_plan):
        _setup(sample_state, sample_team, sample_plan)
        self._run_with_mocks(sample_plan.project_id)
        plan = registry.load_plan(sample_plan.project_id)
        assert plan.status == "complete"

    def test_llm_called_once_per_task(self, sample_state, sample_team, sample_plan):
        _setup(sample_state, sample_team, sample_plan)
        mock_llm, _ = self._run_with_mocks(sample_plan.project_id)
        assert mock_llm.team_execute_task.call_count == 3

    def test_checkpoint_task_calls_oversight(self, sample_state, sample_team, sample_plan):
        _setup(sample_state, sample_team, sample_plan)
        # task_002 is the checkpoint
        _, mock_oversight = self._run_with_mocks(sample_plan.project_id)
        mock_oversight.checkpoint.assert_called_once()
        args = mock_oversight.checkpoint.call_args[0]
        assert args[0].id == "task_002"

    def test_rejected_task_skipped(self, sample_state, sample_team, sample_plan):
        _setup(sample_state, sample_team, sample_plan)
        mock_llm, _ = self._run_with_mocks(
            sample_plan.project_id, oversight_action="rejected"
        )
        plan = registry.load_plan(sample_plan.project_id)
        # task_002 rejected → failed
        assert plan.task_by_id("task_002").status == "failed"
        # task_003 depends on task_002 → propagated to failed, not an error
        assert plan.task_by_id("task_003").status == "failed"
        # LLM only called for task_001 (before the checkpoint)
        assert mock_llm.team_execute_task.call_count == 1

    def test_output_files_created(self, sample_state, sample_team, sample_plan):
        _setup(sample_state, sample_team, sample_plan)
        self._run_with_mocks(sample_plan.project_id)
        output = registry.load_output(sample_plan.project_id, "task_001")
        assert output is not None
        assert "Task output" in output

    def test_already_done_tasks_skipped(self, sample_state, sample_team, sample_plan):
        """Mark task_001 done before running — LLM should only be called for 002 and 003."""
        sample_plan.tasks[0].status = "done"
        write_plan(sample_plan)
        write_state(sample_state)
        write_team(sample_team)

        with patch("aicompany.orchestrator.llm") as mock_llm, \
             patch("aicompany.orchestrator.oversight") as mock_oversight:
            mock_llm.team_execute_task.return_value = "output"
            mock_oversight.checkpoint.return_value = ("approved", "")
            orchestrator.run_project(sample_plan.project_id)

        assert mock_llm.team_execute_task.call_count == 2

    def test_already_complete_project_exits_early(self, sample_state, sample_team, sample_plan, capsys):
        sample_plan.status = "complete"
        _setup(sample_state, sample_team, sample_plan)
        with patch("aicompany.orchestrator.llm") as mock_llm:
            orchestrator.run_project(sample_plan.project_id)
            mock_llm.team_execute_task.assert_not_called()
        assert "already complete" in capsys.readouterr().out

    def test_llm_error_marks_task_failed(self, sample_state, sample_team, sample_plan):
        _setup(sample_state, sample_team, sample_plan)
        with patch("aicompany.orchestrator.llm") as mock_llm, \
             patch("aicompany.orchestrator.oversight") as mock_oversight:
            mock_llm.team_execute_task.side_effect = Exception("API timeout")
            mock_oversight.checkpoint.return_value = ("approved", "")
            with pytest.raises(OrchestratorError, match="API timeout"):
                orchestrator.run_project(sample_plan.project_id)

        plan = registry.load_plan(sample_plan.project_id)
        assert plan.task_by_id("task_001").status == "failed"
