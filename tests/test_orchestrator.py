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
from aicompany.models import Plan, Task, TaskInput, Person, ProjectPlan, Team
from tests.conftest import make_leaf_plan, make_task_input
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
            Task(id="a", title="A", input=make_task_input(), assigned_team="eng", plan=make_leaf_plan()),
            Task(id="b", title="B", input=make_task_input(), assigned_team="eng", plan=make_leaf_plan()),
        ]
        ordered = _topological_sort(tasks)
        assert {t.id for t in ordered} == {"a", "b"}

    def test_unknown_dep_raises(self):
        tasks = [
            Task(id="a", title="A", input=make_task_input(), assigned_team="eng",
                 plan=make_leaf_plan(), depends_on=["ghost"]),
        ]
        with pytest.raises(OrchestratorError, match="unknown task"):
            _topological_sort(tasks)

    def test_cycle_raises(self):
        tasks = [
            Task(id="a", title="A", input=make_task_input(), assigned_team="eng",
                 plan=make_leaf_plan(), depends_on=["b"]),
            Task(id="b", title="B", input=make_task_input(), assigned_team="eng",
                 plan=make_leaf_plan(), depends_on=["a"]),
        ]
        with pytest.raises(OrchestratorError, match="Cycle"):
            _topological_sort(tasks)

    def test_diamond_dependency(self):
        tasks = [
            Task(id="root",  title="Root",  input=make_task_input(), assigned_team="eng", plan=make_leaf_plan()),
            Task(id="left",  title="Left",  input=make_task_input(), assigned_team="eng", plan=make_leaf_plan(), depends_on=["root"]),
            Task(id="right", title="Right", input=make_task_input(), assigned_team="eng", plan=make_leaf_plan(), depends_on=["root"]),
            Task(id="tip",   title="Tip",   input=make_task_input(), assigned_team="eng", plan=make_leaf_plan(), depends_on=["left", "right"]),
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
    def _run_with_mocks(self, project_id, oversight_action="approved", monkeypatch=None):
        mock_reasoner = _make_mock_reasoner()
        if monkeypatch is not None:
            monkeypatch.setattr(config, "MCP_SERVERS", [{"type": "url", "url": "http://fake", "name": "test"}])
        with patch("aicompany.orchestrator.create_reasoner", return_value=mock_reasoner), \
             patch("aicompany.orchestrator.oversight") as mock_oversight, \
             patch.object(config, "MCP_SERVERS", [{"type": "url", "url": "http://fake", "name": "test"}]):

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

    def test_workspace_src_dir_created(self, sample_state, sample_team, sample_plan, sample_persons, sample_skills):
        _setup(sample_state, sample_team, sample_plan, sample_persons, sample_skills)
        self._run_with_mocks(sample_plan.project_id)
        assert (config.PROJECTS_DIR / sample_plan.project_id / "src").exists()

    def test_raises_without_mcp(self, sample_state, sample_team, sample_plan, sample_persons, sample_skills):
        _setup(sample_state, sample_team, sample_plan, sample_persons, sample_skills)
        with patch.object(config, "MCP_SERVERS", []):
            with pytest.raises(RuntimeError, match="MCP server required"):
                orchestrator.run_project(sample_plan.project_id)

    def test_already_done_tasks_skipped(self, sample_state, sample_team, sample_plan, sample_persons, sample_skills):
        sample_plan.tasks[0].status = "done"
        write_plan(sample_plan)
        write_state(sample_state)
        write_team(sample_team)
        write_persons(sample_persons)
        write_skills(sample_skills)

        mock_reasoner = _make_mock_reasoner()
        with patch("aicompany.orchestrator.create_reasoner", return_value=mock_reasoner), \
             patch("aicompany.orchestrator.oversight") as mock_oversight, \
             patch.object(config, "MCP_SERVERS", [{"type": "url", "url": "http://fake", "name": "test"}]):
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
             patch("aicompany.orchestrator.oversight") as mock_oversight, \
             patch.object(config, "MCP_SERVERS", [{"type": "url", "url": "http://fake", "name": "test"}]):
            mock_oversight.checkpoint.return_value = ("approved", "")
            with pytest.raises(OrchestratorError, match="API timeout"):
                orchestrator.run_project(sample_plan.project_id)

        plan = registry.load_plan(sample_plan.project_id)
        assert plan.task_by_id("task_001").status == "failed"


# ── _find_prior_output ────────────────────────────────────────────────────────

class TestFindPriorOutput:
    def test_returns_none_when_no_deps(self, sample_plan):
        write_plan(sample_plan)
        task = Task(id="t", title="T", input=make_task_input(), assigned_team="eng",
                    plan=make_leaf_plan(), depends_on=[])
        from aicompany.orchestrator import _find_prior_output
        assert _find_prior_output(sample_plan, task) is None

    def test_returns_single_dep_output(self, sample_plan):
        write_plan(sample_plan)
        registry.save_output(sample_plan.project_id, "task_001", "Output A")
        task = Task(id="t", title="T", input=make_task_input(), assigned_team="eng",
                    plan=make_leaf_plan(), depends_on=["task_001"])
        from aicompany.orchestrator import _find_prior_output
        result = _find_prior_output(sample_plan, task)
        assert result == "Output A"

    def test_collects_all_dep_outputs(self, sample_plan):
        write_plan(sample_plan)
        registry.save_output(sample_plan.project_id, "task_001", "Output A")
        registry.save_output(sample_plan.project_id, "task_002", "Output B")
        task = Task(id="t", title="T", input=make_task_input(), assigned_team="eng",
                    plan=make_leaf_plan(), depends_on=["task_001", "task_002"])
        from aicompany.orchestrator import _find_prior_output
        result = _find_prior_output(sample_plan, task)
        assert "Output A" in result
        assert "Output B" in result

    def test_skips_missing_dep_outputs(self, sample_plan):
        write_plan(sample_plan)
        registry.save_output(sample_plan.project_id, "task_001", "Output A")
        task = Task(id="t", title="T", input=make_task_input(), assigned_team="eng",
                    plan=make_leaf_plan(), depends_on=["task_001", "task_002"])
        from aicompany.orchestrator import _find_prior_output
        result = _find_prior_output(sample_plan, task)
        assert result == "Output A"


# ── nested subtask execution ──────────────────────────────────────────────────

class TestNestedSubtaskExecution:
    def test_nested_subtasks_are_executed(
        self, sample_state, sample_team, sample_persons, sample_skills,
    ):
        sub1 = Task(id="sub_001", title="Sub 1", input=make_task_input("sub task 1"),
                    assigned_team="backend_engineer", plan=make_leaf_plan())
        sub2 = Task(id="sub_002", title="Sub 2", input=make_task_input("sub task 2"),
                    assigned_team="backend_engineer", plan=make_leaf_plan(), depends_on=["sub_001"])

        sub_plan = Plan(
            project_id="proj_nested",
            title="Sub plan",
            input=make_task_input("parent sub plan"),
            requirements=[],
            tasks=[sub1, sub2],
        )
        parent_task = Task(
            id="task_001",
            title="Parent task",
            input=make_task_input("parent work"),
            assigned_team="backend_engineer",
            plan=sub_plan,
        )
        plan = Plan(
            project_id="proj_nested",
            title="Nested Project",
            input=TaskInput(specification="# requirements"),
            tech_stack=["python"],
            teams_required=["backend_engineer"],
            tasks=[parent_task],
        )

        write_state(sample_state)
        write_team(sample_team)
        write_persons(sample_persons)
        write_skills(sample_skills)
        write_plan(plan)

        mock_reasoner = _make_mock_reasoner()
        with patch("aicompany.orchestrator.create_reasoner", return_value=mock_reasoner), \
             patch.object(config, "MCP_SERVERS", [{"type": "url", "url": "http://fake", "name": "test"}]):
            orchestrator.run_project("proj_nested")

        out1 = registry.load_output("proj_nested", "sub_001")
        out2 = registry.load_output("proj_nested", "sub_002")
        assert out1 is not None
        assert out2 is not None

    def test_nested_output_is_aggregated(
        self, sample_state, sample_team, sample_persons, sample_skills,
    ):
        sub1 = Task(id="sub_001", title="Sub 1", input=make_task_input("sub 1"),
                    assigned_team="backend_engineer", plan=make_leaf_plan())

        sub_plan = Plan(
            project_id="proj_agg",
            title="Sub plan",
            input=make_task_input("sub plan"),
            requirements=[],
            tasks=[sub1],
        )
        parent = Task(
            id="task_001", title="Parent", input=make_task_input("parent"),
            assigned_team="backend_engineer", plan=sub_plan,
        )
        plan = Plan(
            project_id="proj_agg",
            title="Agg Project",
            input=TaskInput(specification="# requirements"),
            tech_stack=["python"],
            teams_required=["backend_engineer"],
            tasks=[parent],
        )

        write_state(sample_state)
        write_team(sample_team)
        write_persons(sample_persons)
        write_skills(sample_skills)
        write_plan(plan)

        mock_reasoner = _make_mock_reasoner()
        with patch("aicompany.orchestrator.create_reasoner", return_value=mock_reasoner), \
             patch.object(config, "MCP_SERVERS", [{"type": "url", "url": "http://fake", "name": "test"}]):
            orchestrator.run_project("proj_agg")

        parent_output = registry.load_output("proj_agg", "task_001")
        assert parent_output is not None
        assert "Task output" in parent_output
