from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from . import config, oversight, registry
from .communication import create_session, run_pattern
from .models import Plan, SessionRules, TaskStub


class OrchestratorError(Exception):
    pass


def _topological_sort(stubs: list) -> list:
    """Kahn's algorithm — returns TaskStubs in dependency order (iterative)."""
    id_to_stub = {s.id: s for s in stubs}
    in_degree = {s.id: 0 for s in stubs}
    dependents: dict[str, list] = {s.id: [] for s in stubs}

    for s in stubs:
        for dep in s.depends_on:
            if dep not in id_to_stub:
                raise OrchestratorError(f"Task {s.id} depends on unknown task {dep}")
            dependents[dep].append(s.id)
            in_degree[s.id] += 1

    queue = deque(s_id for s_id, deg in in_degree.items() if deg == 0)
    result = []
    while queue:
        s_id = queue.popleft()
        result.append(id_to_stub[s_id])
        for dep_id in dependents[s_id]:
            in_degree[dep_id] -= 1
            if in_degree[dep_id] == 0:
                queue.append(dep_id)

    if len(result) != len(stubs):
        raise OrchestratorError("Cycle detected in task dependencies")
    return result


def _build_project_context(
    stub: TaskStub,
    task_plan: Plan,
    workspace: Path,
    id_to_stub: "dict[str, TaskStub] | None" = None,
    project_title: str = "",
    tech_stack: "list[str] | None" = None,
) -> str:
    lines = []
    if project_title:
        lines.append(f"**Project**: {project_title}")
    if tech_stack:
        lines.append(f"**Tech stack**: {', '.join(tech_stack)}")
    lines.append(f"**Task**: {stub.title}")

    def _resolve(dep_id: str) -> str:
        if id_to_stub and dep_id in id_to_stub:
            s = id_to_stub[dep_id]
            suffix = f" → `{s.output_file}`" if s.output_file else ""
            return f"{dep_id} ({s.title}){suffix}"
        return dep_id

    if stub.depends_on:
        lines.append(f"**Depends on**: {', '.join(_resolve(d) for d in stub.depends_on)}")
    if stub.depended_on_by:
        lines.append(f"**Required by**: {', '.join(_resolve(d) for d in stub.depended_on_by)}")
    if workspace:
        lines.append(f"**Workspace**: `{workspace}`")

    if task_plan.requirements:
        req_lines = ["\n## Requirements this task must implement"]
        for req in task_plan.requirements:
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


def _handle_checkpoint(stub: TaskStub, project_id: str, plan: Plan) -> str:
    action, modified = oversight.checkpoint(stub, project_id)
    registry.save_decision(project_id, stub.id, {
        "action": action,
        "task_title": stub.title,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "modified_instructions": modified,
        "user_note": modified if action == "modified" else "",
    })
    plan.decisions_log.append({
        "task_id": stub.id,
        "action": action,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    return action


async def _execute_subtask_plan(
    task_plan: Plan, project_id: str, workspace: Path,
) -> str:
    """Recursively execute sub-tasks inside a composite task plan."""
    sorted_subs = _topological_sort(task_plan.tasks)
    sub_done: set = set()
    outputs: list[str] = []
    for sub_stub in sorted_subs:
        if any(dep not in sub_done for dep in sub_stub.depends_on):
            sub_stub.status = "failed"
            registry.update_task_plan(project_id, task_plan.id, task_plan)
            continue

        if sub_stub.is_checkpoint:
            action = _handle_checkpoint(sub_stub, project_id, task_plan)
            if action == "rejected":
                sub_stub.status = "failed"
            registry.update_task_plan(project_id, task_plan.id, task_plan)
            if action == "rejected":
                continue

        sub_output = await _execute_task(sub_stub, project_id, sub_done, workspace, task_plan.tasks)
        registry.save_output(project_id, sub_stub.id, sub_output)
        sub_stub.status = "done"
        sub_done.add(sub_stub.id)
        registry.update_task_plan(project_id, task_plan.id, task_plan)
        outputs.append(sub_output)
    return "\n\n---\n\n".join(outputs)


def _log(project_id: str, task_id: str, level: str, message: str) -> None:
    print(f"    {message}")
    registry.append_task_log(project_id, task_id, level, message)


async def _execute_task(
    stub: TaskStub, project_id: str, completed_ids: set, workspace: Path,
    sibling_stubs: list | None = None,
) -> str:
    """Load task plan, build context, run communication pattern. Returns output text."""
    task_plan = registry.load_task_plan(project_id, stub.id)

    if task_plan.has_subtasks:
        return await _execute_subtask_plan(task_plan, project_id, workspace)

    team, lead, members, skill_registry = registry.load_team_with_members(stub.assigned_team)
    rules = SessionRules.from_dict(team.communication) if team.communication else SessionRules()

    existing = registry.load_session(project_id, stub.id)
    session = existing if existing else create_session(stub.id, [p.id for p in members], rules)

    orig_add = session.add_message
    def _add_and_save(msg):
        result = orig_add(msg)
        registry.save_session(project_id, session)
        return result
    session.add_message = _add_and_save

    root_plan = registry.load_plan(project_id)
    id_to_stub = {s.id: s for s in (sibling_stubs or root_plan.tasks)}
    context = _build_project_context(
        stub, task_plan, workspace,
        id_to_stub=id_to_stub,
        project_title=root_plan.title,
        tech_stack=root_plan.tech_stack,
    )

    resuming = existing is not None and len(existing.messages) > 0
    registry.append_task_log(project_id, stub.id, "INFO",
                             f"team={stub.assigned_team} pattern={rules.pattern} "
                             f"members={[p.id for p in members]}"
                             + (" [RESUMING]" if resuming else ""))

    def _on_status(msg: str) -> None:
        print(f"    → {msg}")
        registry.append_task_log(project_id, stub.id, "INFO", f"→ {msg}")

    output = await run_pattern(
        pattern_name=rules.pattern,
        session=session, lead=lead, members=members,
        task_title=stub.title,
        task_description=task_plan.input.specification,
        project_context=context,
        workspace=workspace,
        skill_registry=skill_registry,
        on_status=_on_status,
    )
    registry.save_session(project_id, session)
    return output


async def run_project(project_id: str, dry_run: bool = False) -> None:
    plan = registry.load_plan(project_id)

    if plan.status == "complete":
        print(f"Project {project_id} is already complete.")
        return

    plan.status = "running"
    registry.save_plan(plan)

    workspace = config.PROJECTS_DIR / project_id / "src"
    workspace.mkdir(parents=True, exist_ok=True)

    sorted_stubs = _topological_sort(plan.tasks)
    completed_ids = {s.id for s in plan.tasks if s.status == "done"}
    failed_ids = {s.id for s in plan.tasks if s.status == "failed"}

    def _tlog(task_id: str, level: str, msg: str) -> None:
        registry.append_task_log(project_id, task_id, level, msg)

    for stub in sorted_stubs:
        if stub.status == "done":
            print(f"  [skip] {stub.id}: {stub.title} (already done)")
            continue

        if any(dep in failed_ids for dep in stub.depends_on):
            failed_deps = [d for d in stub.depends_on if d in failed_ids]
            print(f"  [skip] {stub.id}: dependency failed or was rejected")
            _tlog(stub.id, "SKIP", f"skipped — dependency failed: {failed_deps}")
            stub.status = "failed"
            failed_ids.add(stub.id)
            registry.save_plan(plan)
            continue

        if not all(dep in completed_ids for dep in stub.depends_on):
            raise OrchestratorError(
                f"Dependencies not satisfied for {stub.id}: {stub.depends_on}"
            )

        if stub.is_checkpoint and not dry_run:
            action = _handle_checkpoint(stub, project_id, plan)
            _tlog(stub.id, "CHECKPOINT", f"decision={action}")
            if action == "rejected":
                stub.status = "failed"
                failed_ids.add(stub.id)
                registry.save_plan(plan)
                print(f"  [skip] {stub.id}: rejected by user")
                continue

        if dry_run:
            print(f"  [dry-run] Would execute: {stub.id} — {stub.title} (team: {stub.assigned_team})")
            completed_ids.add(stub.id)
            continue

        print(f"  [run] {stub.id}: {stub.title} (team: {stub.assigned_team})")
        _tlog(stub.id, "START", f"{stub.title} | team={stub.assigned_team}")
        stub.status = "running"
        registry.save_plan(plan)

        log_token = config.task_log.set(
            lambda level, msg, _tid=stub.id: _tlog(_tid, level, msg)
        )
        try:
            output = await _execute_task(stub, project_id, completed_ids, workspace, plan.tasks)
        except Exception as exc:
            _tlog(stub.id, "ERROR", f"{type(exc).__name__}: {exc}")
            stub.status = "failed"
            registry.save_plan(plan)
            raise OrchestratorError(f"Task {stub.id} failed: {exc}") from exc
        finally:
            config.task_log.reset(log_token)

        rel_path = registry.save_output(project_id, stub.id, output)
        stub.output_file = rel_path
        stub.status = "done"
        completed_ids.add(stub.id)
        registry.save_plan(plan)
        _tlog(stub.id, "DONE", f"output saved → {rel_path}")
        print(f"  [done] {stub.id} → {rel_path}")

    if not dry_run and all(s.status in ("done", "failed") for s in plan.tasks):
        plan.status = "complete"
        registry.save_plan(plan)
        print(f"\nProject {project_id} complete.")
