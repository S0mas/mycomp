"""
CTO planning, HR team creation, and project assembly.

CTO planning runs through the CTO team's PersonAgents (pair_review pattern).
HR team creation uses a one-shot SDK query to create team definitions on demand.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import yaml

from . import config, registry
from .communication import create_session, run_pattern
from .utils import extract_json_block as _extract_json_block
from .models import (
    MAX_PLAN_DEPTH, Person, Plan, Requirement, SessionRules, Skill, TaskInput,
    TaskStub, Team,
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

class CTOPlanning:
    async def run(self, requirements_text: str, state_yaml: str, on_status: callable) -> dict:
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

class HRTeamCreation:
    async def run(self, team_id: str, tech_context: str) -> dict:
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
        result = await HRTeamCreation().run(team_id, tech_context)
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


# ── Requirements scoping ──────────────────────────────────────────────────────

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


# ── Recursive task tree building ──────────────────────────────────────────────

async def _build_task_tree(
    raw_tasks: list[dict],
    project_id: str,
    state_yaml: str,
    parent_requirements: list,
    parent_context: str,
    parent_dir: Path,
    on_status: callable,
    depth: int = 0,
) -> list[TaskStub]:
    """
    Build the task tree for a set of raw task dicts from CTO output.

    For each task:
    - If it signals sub-tasks (non-empty "subtasks" key): run RequirementsValidation →
      CTO planning → PlanValidation → recurse into the sub-plan.
    - Otherwise it is a leaf: create a Plan with the task's own input + scoped requirements.
    Save each task's Plan to parent_dir/tasks/{id}/plan.yaml.
    Return a list of TaskStubs for the parent plan.yaml.
    After all stubs are built, compute depended_on_by (reverse of depends_on).
    """
    if depth >= MAX_PLAN_DEPTH:
        return []

    stubs: list[TaskStub] = []

    for i, raw in enumerate(raw_tasks):
        task_id = raw.get("id", f"task_{i+1:03d}")
        title = raw.get("title", task_id)
        assigned_team = raw.get("assigned_team", "")
        task_dir = parent_dir / "tasks" / task_id

        if raw.get("subtasks"):
            # Non-leaf: recursively plan this task
            spec = raw.get("description", title)
            on_status(f"Recursively planning task: {title} (depth {depth + 1})")

            req_val = RequirementsValidation()
            approved_spec, _ = await req_val.run(spec, on_status=on_status)

            sub_plan_dict = await CTOPlanning().run(approved_spec, state_yaml, on_status)

            plan_val = PlanValidation()
            approved_sub_plan, _ = await plan_val.run(sub_plan_dict, on_status=on_status)

            sub_requirements = [
                Requirement.from_dict(r) for r in approved_sub_plan.get("requirements", [])
            ]
            sub_context = f"Parent task: {title}\n{parent_context}"
            sub_stubs = await _build_task_tree(
                approved_sub_plan.get("tasks", []),
                project_id, state_yaml, sub_requirements,
                sub_context, task_dir, on_status, depth + 1,
            )
            task_plan = Plan(
                id=task_id,
                title=f"{title} — plan",
                input=TaskInput(specification=approved_spec, context=parent_context),
                requirements=sub_requirements,
                tasks=sub_stubs,
                tech_stack=approved_sub_plan.get("tech_stack", []),
                teams_required=approved_sub_plan.get("teams_required", []),
            )
        else:
            # Leaf task
            scoped_reqs = _scope_requirements(
                parent_requirements, set(raw.get("requirement_ids", []))
            )
            task_plan = Plan(
                id=task_id,
                title=f"{title} — plan",
                input=TaskInput(
                    specification=raw.get("description", ""),
                    context=parent_context,
                ),
                requirements=scoped_reqs,
                tasks=[],
            )

        registry.save_task_plan(project_id, task_id, task_plan, parent_dir)

        stub = TaskStub(
            id=task_id,
            title=title,
            assigned_team=assigned_team,
            depends_on=raw.get("depends_on", []),
            depended_on_by=[],
            is_checkpoint=raw.get("is_checkpoint", False),
            status="pending",
        )
        stubs.append(stub)

    # Compute reverse dependency index
    id_to_stub = {s.id: s for s in stubs}
    for stub in stubs:
        for dep_id in stub.depends_on:
            if dep_id in id_to_stub:
                id_to_stub[dep_id].depended_on_by.append(stub.id)

    return stubs


# ── Project assembly ──────────────────────────────────────────────────────────

def _build_parent_context(title: str, tech_stack: list, raw_tasks: list) -> str:
    lines = [f"Project: {title}", f"Tech stack: {', '.join(tech_stack)}"]
    if raw_tasks:
        lines.append("Tasks in this project:")
        lines.extend(f"  - {t.get('title', '?')}" for t in raw_tasks)
    return "\n".join(lines)


async def _assemble_project(
    project_id: str,
    title: str,
    tech_stack: list,
    teams_required: list,
    raw_tasks: list,
    requirements: list,
    requirements_text: str,
    state_yaml: str,
    on_status: callable,
) -> Plan:
    parent_context = _build_parent_context(title, tech_stack, raw_tasks)
    project_root = registry.project_dir(project_id)

    task_stubs = await _build_task_tree(
        raw_tasks=raw_tasks,
        project_id=project_id,
        state_yaml=state_yaml,
        parent_requirements=requirements,
        parent_context=parent_context,
        parent_dir=project_root,
        on_status=on_status,
    )

    return Plan(
        id=project_id,
        title=title,
        input=TaskInput(specification=requirements_text),
        requirements=requirements,
        tech_stack=tech_stack,
        teams_required=teams_required,
        tasks=task_stubs,
    )


# ── Deduplication ─────────────────────────────────────────────────────────────

_DEDUP_LEAD = Person(
    id="dedup_lead",
    name="Deduplication Lead",
    role="lead",
    identity=(
        "You are a software architect leading a deduplication review. "
        "You traverse task plan trees, identify semantically equivalent tasks, "
        "and produce precise merge instructions."
    ),
    knowledge=["software architecture", "dependency graphs"],
    rules=[
        "Output ONLY a ```json block — no prose before or after.",
        'The JSON must have exactly one key: "merges" — a list of merge groups.',
        'Each merge group: {"keep": "<deepest_task_id>", "remove": ["<shallower_id>", ...]}',
        "Keep the task at the DEEPEST level among duplicates (deepest in the directory tree).",
        "Remove shallower copies. Their dependents must be redirected to the kept task.",
        'If no duplicates exist, return {"merges": []}.',
    ],
)

_DEDUP_VALIDATORS = [
    Person(
        id="dedup_semantic",
        name="Semantic Analyst",
        role="reviewer",
        identity=(
            "You review task plans to identify tasks with semantically equivalent outcomes "
            "that appear in different branches of the task tree."
        ),
        knowledge=["requirements analysis", "task decomposition"],
        rules=["Focus only on semantic equivalence — identical title alone is not enough."],
    ),
    Person(
        id="dedup_deps",
        name="Dependency Checker",
        role="reviewer",
        identity=(
            "You verify that after a merge the dependency graph remains consistent: "
            "no dangling references, no new cycles."
        ),
        knowledge=["dependency graphs", "topological ordering"],
        rules=["Flag any merge that would introduce a dependency cycle."],
    ),
]


def _collect_all_plan_paths(project_dir: Path) -> list[Path]:
    """Return all plan.yaml paths in the task tree, BFS order."""
    paths = [project_dir / "plan.yaml"]
    queue = [project_dir / "tasks"]
    while queue:
        tasks_dir = queue.pop(0)
        if not tasks_dir.exists():
            continue
        for child in sorted(tasks_dir.iterdir()):
            if child.is_dir():
                plan_file = child / "plan.yaml"
                if plan_file.exists():
                    paths.append(plan_file)
                queue.append(child / "tasks")
    return paths


def _apply_dedup_merges(merges: list[dict], project_id: str) -> None:
    """Apply AI-produced merge instructions to the on-disk plan tree."""
    if not merges:
        return

    proj_root = registry.project_dir(project_id)

    for merge in merges:
        keep_id = merge.get("keep")
        remove_ids: list[str] = merge.get("remove", [])
        if not keep_id or not remove_ids:
            continue

        # Redirect all depends_on references from removed IDs → keep_id
        for plan_path in _collect_all_plan_paths(proj_root):
            with plan_path.open(encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if not isinstance(data, dict):
                continue

            changed = False
            for stub_dict in data.get("tasks", []):
                new_deps = []
                for dep in stub_dict.get("depends_on", []):
                    if dep in remove_ids:
                        if keep_id not in new_deps:
                            new_deps.append(keep_id)
                        changed = True
                    else:
                        new_deps.append(dep)
                stub_dict["depends_on"] = new_deps

                # Remove stubs for deleted tasks
                if stub_dict.get("id") in remove_ids:
                    changed = True  # will be filtered below

            # Filter out removed stubs
            original_count = len(data.get("tasks", []))
            data["tasks"] = [
                s for s in data.get("tasks", []) if s.get("id") not in remove_ids
            ]
            if len(data["tasks"]) != original_count:
                changed = True

            if changed:
                with plan_path.open("w", encoding="utf-8") as f:
                    yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

        # Recompute depended_on_by for all affected plans
        for plan_path in _collect_all_plan_paths(proj_root):
            with plan_path.open(encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if not isinstance(data, dict):
                continue
            stubs = data.get("tasks", [])
            id_to_stub = {s["id"]: s for s in stubs}
            for s in stubs:
                s["depended_on_by"] = []
            for s in stubs:
                for dep_id in s.get("depends_on", []):
                    if dep_id in id_to_stub:
                        id_to_stub[dep_id]["depended_on_by"].append(s["id"])
            with plan_path.open("w", encoding="utf-8") as f:
                yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

        # Delete removed task directories
        for remove_id in remove_ids:
            node = registry._find_task_node(proj_root, remove_id)
            if node and node.exists():
                import shutil
                shutil.rmtree(node)


class Deduplication:
    async def run(self, project_id: str, on_status: callable) -> None:
        on_status("Running deduplication review...")
        proj_root = registry.project_dir(project_id)

        task_desc = (
            f"Project root: {proj_root}/plan.yaml\n\n"
            "Use the Read tool to traverse the full task tree (plan.yaml → tasks/*/plan.yaml → ...).\n"
            "Identify semantically duplicate tasks that appear in different branches.\n"
            "For each set of duplicates: keep the DEEPEST one (deepest directory nesting), "
            "remove the shallower copies.\n\n"
            "Output a JSON merge plan with exactly the structure described in your rules."
        )

        session = create_session(
            "dedup_review",
            [_DEDUP_LEAD.id] + [v.id for v in _DEDUP_VALIDATORS],
            SessionRules(pattern="lead_delegates"),
        )

        raw_output = await run_pattern(
            pattern_name="lead_delegates",
            session=session,
            lead=_DEDUP_LEAD,
            members=[_DEDUP_LEAD] + _DEDUP_VALIDATORS,
            task_title="Deduplication Review",
            task_description=task_desc,
            project_context="",
            workspace=proj_root,
            on_status=on_status,
        )

        try:
            merge_plan = _extract_json_block(raw_output)
            merges = merge_plan.get("merges", [])
        except Exception:
            on_status("Deduplication: could not parse merge plan — skipping")
            return

        if not merges:
            on_status("Deduplication: no duplicates found")
            return

        on_status(f"Deduplication: applying {len(merges)} merge(s)...")
        _apply_dedup_merges(merges, project_id)


# ── Entry point ───────────────────────────────────────────────────────────────

async def plan_and_create_project(
    requirements_text: str,
    on_status: callable = None,
) -> PlanResult:
    _status = on_status or (lambda msg: None)

    # 1. Validate top-level requirements
    req_val = RequirementsValidation()
    approved_text, _ = await req_val.run(requirements_text, on_status=_status)

    state = registry.load_state()
    state_yaml = yaml.dump(state.to_dict(), default_flow_style=False)

    # 2. CTO produces plan
    plan_dict = await CTOPlanning().run(approved_text, state_yaml, _status)

    # 3. Validate the CTO plan
    plan_val = PlanValidation()
    plan_dict, _ = await plan_val.run(plan_dict, on_status=_status)

    title = plan_dict.get("title", "Untitled Project")
    tech_stack = plan_dict.get("tech_stack", [])
    teams_required = plan_dict.get("teams_required", [])
    raw_tasks = plan_dict.get("tasks", [])
    requirements = [Requirement.from_dict(r) for r in plan_dict.get("requirements", [])]

    created_teams = await _create_missing_teams(teams_required, tech_stack, _status)
    _update_technologies(tech_stack)

    project_id = f"proj_{uuid.uuid4().hex[:8]}"
    registry.create_project_dir(project_id, requirements_text)
    if requirements:
        registry.save_requirements(project_id, requirements)

    # 4. Build recursive task tree (saves each task's plan.yaml as it goes)
    plan = await _assemble_project(
        project_id=project_id,
        title=title,
        tech_stack=tech_stack,
        teams_required=teams_required,
        raw_tasks=raw_tasks,
        requirements=requirements,
        requirements_text=requirements_text,
        state_yaml=state_yaml,
        on_status=_status,
    )
    registry.save_plan(plan)

    # 5. Post-planning deduplication review
    await Deduplication().run(project_id, _status)

    # Reload plan after deduplication may have modified it
    plan = registry.load_plan(project_id)

    return PlanResult(
        project_id=project_id,
        plan=plan,
        created_teams=created_teams,
    )
