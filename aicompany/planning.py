"""
CTO planning, HR team creation, and project assembly.

CTO planning runs through the CTO team's PersonAgents (pair_review pattern).
HR team creation uses a one-shot SDK query to create team definitions on demand.
"""
from __future__ import annotations

import uuid

import yaml

from . import config, registry
from .communication import create_session, run_pattern
from .utils import extract_json_block as _extract_json_block
from .models import (
    MAX_PLAN_DEPTH, Person, Plan, Requirement, SessionRules, Skill, Task, TaskInput, Team,
)
from .validation import RequirementsValidation, PlanValidation, ValidationError


# ── HR system prompt ──────────────────────────────────────────────────────────

_HR_SYSTEM = """\
You are an HR manager for an AI software company. You design software engineering teams.

Return ONLY a ```json block with exactly this schema — no prose before or after:

```json
{
  "team": {
    "id": "<team_id>",
    "name": "<Human-readable team name>",
    "skills": ["skill_id_1"],
    "members": ["person_id_1", "person_id_2"],
    "lead_id": "person_id_1",
    "communication": {"pattern": "pair_review", "max_rounds": 4}
  },
  "persons": [
    {
      "id": "unique_snake_id",
      "name": "Full Name",
      "role": "lead",
      "identity": "You are ... (2-3 sentences: expertise, approach, style)",
      "skills": [],
      "knowledge": ["specific technical knowledge point"],
      "rules": ["a behavioral constraint this person always follows"],
      "tools": []
    }
  ],
  "skills": []
}
```

Rules:
- Include a lead and at least one coder or reviewer.
- Roles must be one of: lead, coder, reviewer, tester.
- IDs are snake_case, unique, descriptive (e.g. be_lead, be_coder_1).
- Identity must describe the persona clearly so the agent knows how to behave.
- knowledge and rules shape how the agent thinks — be specific and actionable.
"""


class PlanResult:
    def __init__(
        self,
        project_id: str,
        plan: Plan,
        created_teams: list[str],
    ) -> None:
        self.project_id = project_id
        self.plan = plan
        self.created_teams = created_teams


# ── CTO planning ──────────────────────────────────────────────────────────────

async def _run_cto_planning(requirements_text: str, state_yaml: str, on_status: callable) -> dict:
    on_status("CTO team is analysing requirements...")
    team, lead, members, skill_registry = registry.load_team_with_members("cto_team")
    rules = SessionRules.from_dict(team.communication) if team.communication else SessionRules()
    session = create_session("cto_planning", [p.id for p in members], rules)

    cto_output = await run_pattern(
        pattern_name=rules.pattern,
        session=session, lead=lead, members=members,
        task_title="Project Planning",
        task_description=(
            f"## Client Requirements\n\n{requirements_text}\n\n"
            f"## Current Company Registry (YAML)\n\n```yaml\n{state_yaml}\n```"
        ),
        project_context="",
        workspace=config.BASE_DIR,
        skill_registry=skill_registry,
        on_status=on_status,
    )
    return _extract_json_block(cto_output)


# ── HR team creation ──────────────────────────────────────────────────────────

async def _hr_create_team(team_id: str, tech_context: str) -> dict:
    """Use a one-shot SDK query to create a team definition."""
    from claude_code_sdk import query, ClaudeCodeOptions, AssistantMessage, TextBlock

    prompt = (
        f"Create a software engineering team with id='{team_id}'.\n"
        f"Technology context: {tech_context}"
    )
    text = ""
    async for msg in query(
        prompt=prompt,
        options=ClaudeCodeOptions(
            system_prompt=_HR_SYSTEM,
            permission_mode="bypassPermissions",
            max_turns=3,
        ),
    ):
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock) and block.text:
                    text += block.text
    return _extract_json_block(text)


async def _create_missing_teams(
    teams_required: list[str], tech_stack: list[str], on_status: callable,
) -> list[str]:
    state = registry.load_state()
    missing = [tid for tid in teams_required if tid not in state.team_ids()]
    created: list[str] = []
    tech_context = ", ".join(tech_stack)

    for team_id in missing:
        on_status(f"Team '{team_id}' not found — HR is creating it...")
        result = await _hr_create_team(team_id, tech_context)
        team_data = result.get("team", result)
        team_data["id"] = team_id
        for sd in result.get("skills", []):
            registry.save_skill(Skill.from_dict(sd))
        for pd in result.get("persons", []):
            registry.save_person(Person.from_dict(pd))
        registry.save_team(Team.from_dict(team_data))
        created.append(team_id)

    return created


# ── Technology tracking ───────────────────────────────────────────────────────

def _update_technologies(tech_stack: list[str]) -> None:
    state = registry.load_state()
    seen_lower = {t.lower() for t in state.technologies_seen}
    for tech in tech_stack:
        if tech.lower() not in seen_lower:
            state.technologies_seen.append(tech)
            seen_lower.add(tech.lower())
    registry.save_state(state)


# ── Project assembly ──────────────────────────────────────────────────────────

def _build_parent_context(title: str, tech_stack: list, raw_tasks: list) -> str:
    lines = [f"Project: {title}", f"Tech stack: {', '.join(tech_stack)}"]
    if raw_tasks:
        lines.append("Tasks in this project:")
        lines.extend(f"  - {t.get('title', '?')}" for t in raw_tasks)
    return "\n".join(lines)


def _scope_requirements(requirements: list, req_ids: set) -> list:
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
    project_id: str, title: str, tech_stack: list, teams_required: list,
    raw_tasks: list, requirements: list, requirements_text: str,
) -> Plan:
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


# ── Recursive task expansion ──────────────────────────────────────────────────

async def _expand_tasks_recursively(
    raw_tasks: list[dict],
    state_yaml: str,
    on_status: callable,
    depth: int = 0,
) -> list[dict]:
    """Expand any task that signals further decomposition via a non-empty "subtasks" key.

    A task is a leaf when task.get("subtasks", []) is empty or absent.
    Leaf tasks are returned as-is. Non-leaf tasks are recursively planned:
      1. RequirementsValidation on the task description
      2. CTO planning to produce a sub-plan
      3. PlanValidation on the sub-plan
      4. Recurse on sub-plan tasks

    Recursion is capped at MAX_PLAN_DEPTH to guard against runaway LLM output.
    """
    if depth >= MAX_PLAN_DEPTH:
        return raw_tasks

    result: list[dict] = []
    for task in raw_tasks:
        subtask_specs = task.get("subtasks", [])
        if not subtask_specs:
            result.append(task)
            continue

        title = task.get("title", task.get("id", "?"))
        on_status(f"Recursively planning task: {title} (depth {depth + 1})")

        spec = task.get("description", task.get("title", ""))

        req_val = RequirementsValidation()
        approved_spec, _ = await req_val.run(spec, on_status=on_status)

        sub_plan_dict = await _run_cto_planning(approved_spec, state_yaml, on_status)

        plan_val = PlanValidation()
        approved_sub_plan, _ = await plan_val.run(sub_plan_dict, on_status=on_status)

        expanded = await _expand_tasks_recursively(
            approved_sub_plan.get("tasks", []), state_yaml, on_status, depth + 1,
        )
        result.extend(expanded)

    return result


# ── Entry point ───────────────────────────────────────────────────────────────

async def plan_and_create_project(
    requirements_text: str,
    on_status: callable = None,
) -> PlanResult:
    _status = on_status or (lambda msg: None)

    # 1. Validate top-level requirements (fix loop embedded in RequirementsValidation)
    req_val = RequirementsValidation()
    approved_text, _ = await req_val.run(requirements_text, on_status=_status)
    # ValidationError propagates to caller if rejected after max attempts

    state = registry.load_state()
    state_yaml = yaml.dump(state.to_dict(), default_flow_style=False)

    # 2. CTO produces plan
    plan_dict = await _run_cto_planning(approved_text, state_yaml, _status)

    # 3. Validate the CTO plan
    plan_val = PlanValidation()
    plan_dict, _ = await plan_val.run(plan_dict, on_status=_status)

    # 4. Recursively expand any tasks that signal further decomposition
    plan_dict["tasks"] = await _expand_tasks_recursively(
        plan_dict.get("tasks", []), state_yaml, _status,
    )

    title = plan_dict.get("title", "Untitled Project")
    tech_stack = plan_dict.get("tech_stack", [])
    teams_required = plan_dict.get("teams_required", [])
    raw_tasks = plan_dict.get("tasks", [])
    requirements = [Requirement.from_dict(r) for r in plan_dict.get("requirements", [])]

    created_teams = await _create_missing_teams(teams_required, tech_stack, _status)
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
        created_teams=created_teams,
    )
