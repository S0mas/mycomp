from __future__ import annotations

from collections import deque
from datetime import datetime, timezone

from . import config, oversight, registry
from .communication import create_session, run_pattern
from .models import Plan, SessionRules, Task
from .reasoner import create_reasoner


class OrchestratorError(Exception):
    pass


def _topological_sort(tasks: list) -> list:
    """Kahn's algorithm — returns tasks in dependency order (iterative, no recursion)."""
    id_to_task = {t.id: t for t in tasks}
    in_degree = {t.id: 0 for t in tasks}
    dependents: dict[str, list] = {t.id: [] for t in tasks}

    for t in tasks:
        for dep in t.depends_on:
            if dep not in id_to_task:
                raise OrchestratorError(f"Task {t.id} depends on unknown task {dep}")
            dependents[dep].append(t.id)
            in_degree[t.id] += 1

    queue = deque(t_id for t_id, deg in in_degree.items() if deg == 0)
    result = []
    while queue:
        t_id = queue.popleft()
        result.append(id_to_task[t_id])
        for dep_id in dependents[t_id]:
            in_degree[dep_id] -= 1
            if in_degree[dep_id] == 0:
                queue.append(dep_id)

    if len(result) != len(tasks):
        raise OrchestratorError("Cycle detected in task dependencies")
    return result


def _build_project_context(plan: Plan, completed_ids: set, workspace: str = "",
                           task: Task | None = None) -> str:
    """
    Assemble runtime execution context for a task.
    Parent context (baked in at planning time) comes from task.input.context.
    Requirements come from task.plan.requirements — no parent plan lookup needed.
    """
    lines = []
    if task and task.input.context:
        lines.append(task.input.context)
        lines.append("")

    done_titles = [t.title for t in plan.tasks if t.id in completed_ids]
    lines += [f"**Project**: {plan.title}", f"**Tech stack**: {', '.join(plan.tech_stack)}"]
    if done_titles:
        lines.append(f"**Completed tasks**: {', '.join(done_titles)}")
    if workspace:
        lines.append(f"**Workspace**: `{workspace}`")

    if task and task.plan.requirements:
        req_lines = ["\n## Requirements this task must implement"]
        for req in task.plan.requirements:
            if req.sub_requirements:
                for sub in req.sub_requirements:
                    req_lines.append(f"\n### {sub.id} — {sub.title}")
                    req_lines.append(sub.description)
                    if sub.acceptance_criteria:
                        req_lines.append("**Acceptance criteria:**")
                        req_lines.extend(f"- {ac}" for ac in sub.acceptance_criteria)
            else:
                req_lines += [f"\n### {req.id} — {req.title}", req.description]
        if len(req_lines) > 1:
            lines.extend(req_lines)

    return "\n".join(lines)


def _find_prior_output(plan: Plan, task: Task) -> str | None:
    outputs = [
        output for dep_id in task.depends_on
        if (output := registry.load_output(plan.project_id, dep_id))
    ]
    return "\n\n---\n\n".join(outputs) if outputs else None


def _handle_checkpoint(
    task: Task, prior_output: str | None, project_id: str, plan: Plan,
) -> str:
    """
    Run the human checkpoint gate. Returns 'approved', 'rejected', or 'modified'.
    On 'modified', appends the user override to task.input.specification.
    """
    action, modified = oversight.checkpoint(task, prior_output, project_id)
    registry.save_decision(project_id, task.id, {
        "action": action,
        "task_title": task.title,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "modified_instructions": modified,
        "user_note": modified if action == "modified" else "",
    })
    plan.decisions_log.append({
        "task_id": task.id,
        "action": action,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    if action == "modified":
        task.input.specification += f"\n\n**User override**: {modified}"
    return action


def _execute_subtask_plan(
    sub_plan: Plan, completed_ids: set, workspace: str, project_id: str,
) -> str:
    """Recursively execute sub-tasks inside a composite task plan."""
    sorted_subs = _topological_sort(sub_plan.tasks)
    sub_done: set = set()
    outputs: list[str] = []
    for sub in sorted_subs:
        if any(dep not in sub_done for dep in sub.depends_on):
            sub.status = "failed"
            continue
        sub_output = _execute_task(sub, sub_plan, sub_done, workspace, project_id)
        registry.save_output(project_id, sub.id, sub_output)
        sub.status = "done"
        sub_done.add(sub.id)
        outputs.append(sub_output)
    return "\n\n---\n\n".join(outputs)


def _log(project_id: str, task_id: str, level: str, message: str) -> None:
    print(f"    {message}")
    registry.append_task_log(project_id, task_id, level, message)


def _execute_task(
    task: Task, plan: Plan, completed_ids: set, workspace: str, project_id: str,
) -> str:
    """Load team, build context, run communication pattern. Returns output text."""
    if task.plan.has_subtasks:
        return _execute_subtask_plan(task.plan, completed_ids, workspace, project_id)

    team, lead, members, skill_registry = registry.load_team_with_members(task.assigned_team)
    rules = SessionRules.from_dict(team.communication) if team.communication else SessionRules()
    session = create_session(task.id, [p.id for p in members], rules)
    context = _build_project_context(plan, completed_ids, workspace, task)
    reasoner = create_reasoner()
    reasoner.setup(members, skill_registry)

    registry.append_task_log(project_id, task.id, "INFO",
                             f"team={task.assigned_team} pattern={rules.pattern} "
                             f"max_rounds={rules.max_rounds} members={[p.id for p in members]}")

    def _on_status(msg: str) -> None:
        print(f"    → {msg}")
        registry.append_task_log(project_id, task.id, "INFO", f"→ {msg}")

    output = run_pattern(
        pattern_name=rules.pattern,
        session=session, lead=lead, members=members,
        task_title=task.title,
        task_description=task.input.specification,
        project_context=context,
        reasoner=reasoner, skill_registry=skill_registry,
        on_status=_on_status,
        workspace=workspace,
    )
    registry.save_session(project_id, session)
    return output


def run_project(project_id: str, dry_run: bool = False) -> None:
    plan = registry.load_plan(project_id)

    if plan.status == "complete":
        print(f"Project {project_id} is already complete.")
        return

    plan.status = "running"
    registry.save_plan(plan)

    workspace = f"projects/{project_id}/src"
    (config.PROJECTS_DIR / project_id / "src").mkdir(parents=True, exist_ok=True)

    sorted_tasks = _topological_sort(plan.tasks)
    completed_ids = {t.id for t in plan.tasks if t.status == "done"}
    failed_ids = {t.id for t in plan.tasks if t.status == "failed"}

    def _tlog(task_id: str, level: str, msg: str) -> None:
        registry.append_task_log(project_id, task_id, level, msg)

    for task in sorted_tasks:
        if task.status == "done":
            print(f"  [skip] {task.id}: {task.title} (already done)")
            continue

        if any(dep in failed_ids for dep in task.depends_on):
            failed_deps = [d for d in task.depends_on if d in failed_ids]
            msg = f"skipped — dependency failed: {failed_deps}"
            print(f"  [skip] {task.id}: dependency failed or was rejected")
            _tlog(task.id, "SKIP", msg)
            task.status = "failed"
            failed_ids.add(task.id)
            registry.save_plan(plan)
            continue

        if not all(dep in completed_ids for dep in task.depends_on):
            raise OrchestratorError(
                f"Dependencies not satisfied for {task.id}: {task.depends_on}"
            )

        prior_output = _find_prior_output(plan, task)

        if task.is_checkpoint and not dry_run:
            action = _handle_checkpoint(task, prior_output, project_id, plan)
            _tlog(task.id, "CHECKPOINT", f"decision={action}")
            if action == "rejected":
                task.status = "failed"
                failed_ids.add(task.id)
                registry.save_plan(plan)
                print(f"  [skip] {task.id}: rejected by user")
                continue

        if dry_run:
            print(f"  [dry-run] Would execute: {task.id} — {task.title} (team: {task.assigned_team})")
            completed_ids.add(task.id)
            continue

        print(f"  [run] {task.id}: {task.title} (team: {task.assigned_team})")
        _tlog(task.id, "START", f"{task.title} | team={task.assigned_team}")
        task.status = "running"
        registry.save_plan(plan)

        log_token = config.task_log.set(
            lambda level, msg, _tid=task.id: _tlog(_tid, level, msg)
        )
        try:
            output = _execute_task(task, plan, completed_ids, workspace, project_id)
        except Exception as exc:
            _tlog(task.id, "ERROR", f"{type(exc).__name__}: {exc}")
            task.status = "failed"
            registry.save_plan(plan)
            raise OrchestratorError(f"Task {task.id} failed: {exc}") from exc
        finally:
            config.task_log.reset(log_token)

        rel_path = registry.save_output(project_id, task.id, output)
        task.output_file = rel_path
        task.status = "done"
        completed_ids.add(task.id)
        registry.save_plan(plan)
        _tlog(task.id, "DONE", f"output saved → {rel_path}")
        print(f"  [done] {task.id} → {rel_path}")

    if not dry_run and all(t.status in ("done", "failed") for t in plan.tasks):
        plan.status = "complete"
        registry.save_plan(plan)
        print(f"\nProject {project_id} complete.")
