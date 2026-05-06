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
    for dep_id in reversed(task.depends_on):
        output = registry.load_output(plan.project_id, dep_id)
        if output:
            return output
    return None


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


def _execute_task(
    task: Task, plan: Plan, completed_ids: set, workspace: str, project_id: str,
) -> str:
    """Load team, build context, run communication pattern. Returns output text."""
    team, lead, members, skill_registry = registry.load_team_with_members(task.assigned_team)
    rules = SessionRules.from_dict(team.communication) if team.communication else SessionRules()
    session = create_session(task.id, [p.id for p in members], rules)
    context = _build_project_context(plan, completed_ids, workspace, task)
    reasoner = create_reasoner()
    reasoner.setup(members, skill_registry)
    output = run_pattern(
        pattern_name=rules.pattern,
        session=session, lead=lead, members=members,
        task_title=task.title,
        task_description=task.input.specification,
        project_context=context,
        reasoner=reasoner, skill_registry=skill_registry,
        on_status=lambda msg: print(f"    → {msg}"),
        workspace=workspace,
    )
    registry.save_session(project_id, session)
    return output


def run_project(project_id: str, dry_run: bool = False) -> None:
    plan = registry.load_plan(project_id)

    if plan.status == "complete":
        print(f"Project {project_id} is already complete.")
        return

    if not config.MCP_SERVERS and not dry_run:
        raise RuntimeError(
            "MCP server required for project execution. "
            "Start one with ./scripts/start_mcp.sh and set AICOMPANY_MCP_SERVERS."
        )

    plan.status = "running"
    registry.save_plan(plan)

    workspace = f"projects/{project_id}/src"
    (config.PROJECTS_DIR / project_id / "src").mkdir(parents=True, exist_ok=True)

    sorted_tasks = _topological_sort(plan.tasks)
    completed_ids = {t.id for t in plan.tasks if t.status == "done"}
    failed_ids = {t.id for t in plan.tasks if t.status == "failed"}

    for task in sorted_tasks:
        if task.status == "done":
            print(f"  [skip] {task.id}: {task.title} (already done)")
            continue

        if any(dep in failed_ids for dep in task.depends_on):
            print(f"  [skip] {task.id}: dependency failed or was rejected")
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
        task.status = "running"
        registry.save_plan(plan)

        try:
            output = _execute_task(task, plan, completed_ids, workspace, project_id)
        except Exception as exc:
            task.status = "failed"
            registry.save_plan(plan)
            raise OrchestratorError(f"Task {task.id} failed: {exc}") from exc

        rel_path = registry.save_output(project_id, task.id, output)
        task.output_file = rel_path
        task.status = "done"
        completed_ids.add(task.id)
        registry.save_plan(plan)
        print(f"  [done] {task.id} → {rel_path}")

    if not dry_run and all(t.status in ("done", "failed") for t in plan.tasks):
        plan.status = "complete"
        registry.save_plan(plan)
        print(f"\nProject {project_id} complete.")
