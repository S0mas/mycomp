"""
CTO planning, HR team creation, and project assembly.

Owns the multi-step flow: CTO plans → HR creates teams → project is assembled
and persisted. Each step is extracted into its own focused helper.
"""
from __future__ import annotations

import uuid

import yaml

from . import config, llm, registry
from .communication import create_session, run_pattern
from .models import (
    Person, Plan, Requirement, SessionRules, Skill, Task, TaskInput, Team,
)
from .reasoner import create_reasoner
from .validation import validate_cto_plan, validate_hr_response


class PlanResult:
    """Outcome of CTO planning + HR team creation."""

    def __init__(
        self,
        project_id: str,
        plan: Plan,
        plan_warnings: list[str],
        created_teams: list[str],
        hr_warnings: dict[str, list[str]],
    ) -> None:
        self.project_id = project_id
        self.plan = plan
        self.plan_warnings = plan_warnings
        self.created_teams = created_teams
        self.hr_warnings = hr_warnings


# ── CTO planning ──────────────────────────────────────────────────────────────

def _run_cto_planning(requirements_text: str, state_yaml: str, on_status: callable) -> dict:
    """Run the CTO team to produce a project plan dict."""
    on_status("CTO team is analysing requirements...")
    team, lead, members, skill_registry = registry.load_team_with_members("cto_team")
    rules = SessionRules.from_dict(team.communication) if team.communication else SessionRules()
    session = create_session("cto_planning", [p.id for p in members], rules)
    reasoner = create_reasoner()
    reasoner.setup(members, skill_registry)

    task_description = (
        f"## Client Requirements\n\n{requirements_text}\n\n"
        f"## Current Company Registry (YAML)\n\n```yaml\n{state_yaml}\n```"
    )
    cto_output = run_pattern(
        pattern_name=rules.pattern,
        session=session, lead=lead, members=members,
        task_title="Project Planning",
        task_description=task_description,
        project_context="",
        reasoner=reasoner, skill_registry=skill_registry,
        workspace="", on_status=on_status,
    )
    return llm.extract_json_block(cto_output)


# ── HR team creation ──────────────────────────────────────────────────────────

def _create_missing_teams(
    teams_required: list[str], tech_stack: list[str], on_status: callable,
) -> tuple[list[str], dict[str, list[str]]]:
    """Call HR to create any teams not yet in the registry. Returns (created_ids, warnings)."""
    state = registry.load_state()
    missing = [tid for tid in teams_required if tid not in state.team_ids()]
    created: list[str] = []
    warnings: dict[str, list[str]] = {}
    tech_context = ", ".join(tech_stack)

    for team_id in missing:
        on_status(f"Team '{team_id}' not found — HR is creating it...")
        result = llm.hr_create_team(team_id, tech_context)
        errors = validate_hr_response(result, team_id)
        if errors:
            warnings[team_id] = errors

        team_data = result.get("team", result)
        team_data["id"] = team_id
        for sd in result.get("skills", []):
            registry.save_skill(Skill.from_dict(sd))
        for pd in result.get("persons", []):
            registry.save_person(Person.from_dict(pd))
        registry.save_team(Team.from_dict(team_data))
        created.append(team_id)

    return created, warnings


# ── Technology tracking ───────────────────────────────────────────────────────

def _update_technologies(tech_stack: list[str]) -> None:
    """Append newly seen technologies to company state."""
    state = registry.load_state()
    seen_lower = {t.lower() for t in state.technologies_seen}
    for tech in tech_stack:
        if tech.lower() not in seen_lower:
            state.technologies_seen.append(tech)
            seen_lower.add(tech.lower())
    registry.save_state(state)


# ── Project assembly ──────────────────────────────────────────────────────────

def _build_parent_context(title: str, tech_stack: list, raw_tasks: list) -> str:
    """High-level project summary baked into every task's TaskInput.context."""
    lines = [f"Project: {title}", f"Tech stack: {', '.join(tech_stack)}"]
    if raw_tasks:
        lines.append("Tasks in this project:")
        lines.extend(f"  - {t.get('title', '?')}" for t in raw_tasks)
    return "\n".join(lines)


def _scope_requirements(requirements: list, req_ids: set) -> list:
    """Return requirements scoped to the sub-requirement IDs a task addresses."""
    if not req_ids:
        return []
    scoped = []
    for req in requirements:
        matching_subs = [s for s in req.sub_requirements if s.id in req_ids]
        if matching_subs:
            scoped.append(Requirement(
                id=req.id, title=req.title, description=req.description,
                sub_requirements=matching_subs, status=req.status,
            ))
        elif req.id in req_ids:
            scoped.append(req)
    return scoped


def _assemble_project(
    project_id: str,
    title: str,
    tech_stack: list,
    teams_required: list,
    raw_tasks: list,
    requirements: list,
    requirements_text: str,
) -> Plan:
    """Build Plan + leaf Tasks from CTO output. Pure transformation, no I/O."""
    parent_context = _build_parent_context(title, tech_stack, raw_tasks)
    tasks = []
    for i, raw in enumerate(raw_tasks):
        task_id = raw.get("id", f"task_{i+1:03d}")
        task_input = TaskInput(specification=raw.get("description", ""), context=parent_context)
        task_plan = Plan(
            project_id="",
            title=f"{raw['title']} — plan",
            input=task_input,
            requirements=_scope_requirements(requirements, set(raw.get("requirement_ids", []))),
            tasks=[],
        )
        tasks.append(Task(
            id=task_id,
            title=raw["title"],
            input=task_input,
            assigned_team=raw["assigned_team"],
            plan=task_plan,
            depends_on=raw.get("depends_on", []),
            is_checkpoint=raw.get("is_checkpoint", False),
            output_file=f"outputs/{task_id}.md",
        ))
    return Plan(
        project_id=project_id,
        title=title,
        input=TaskInput(specification=requirements_text),
        requirements=requirements,
        tech_stack=tech_stack,
        teams_required=teams_required,
        tasks=tasks,
    )


# ── Orchestration ─────────────────────────────────────────────────────────────

def plan_and_create_project(
    requirements_text: str,
    on_status: callable = None,
) -> PlanResult:
    """
    Run CTO planning, create missing teams via HR, assemble and persist the project.
    Returns a PlanResult with the plan and metadata.
    """
    _status = on_status or (lambda msg: None)

    state = registry.load_state()
    state_yaml = yaml.dump(state.to_dict(), default_flow_style=False)

    plan_dict = _run_cto_planning(requirements_text, state_yaml, _status)
    plan_warnings = validate_cto_plan(plan_dict)

    title = plan_dict.get("title", "Untitled Project")
    tech_stack = plan_dict.get("tech_stack", [])
    teams_required = plan_dict.get("teams_required", [])
    raw_tasks = plan_dict.get("tasks", [])
    requirements = [Requirement.from_dict(r) for r in plan_dict.get("requirements", [])]

    created_teams, hr_warnings = _create_missing_teams(teams_required, tech_stack, _status)
    _update_technologies(tech_stack)

    project_id = f"proj_{uuid.uuid4().hex[:8]}"
    plan = _assemble_project(project_id, title, tech_stack, teams_required,
                             raw_tasks, requirements, requirements_text)

    registry.create_project_dir(project_id, requirements_text)
    registry.save_plan(plan)
    if requirements:
        registry.save_requirements(project_id, requirements)

    return PlanResult(
        project_id=project_id,
        plan=plan,
        plan_warnings=plan_warnings,
        created_teams=created_teams,
        hr_warnings=hr_warnings,
    )
