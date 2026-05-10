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

_HR_SCHEMA = """\
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
}"""

_HR_SYSTEM = f"""\
You are an HR manager for an AI software company. You design software engineering teams.

Write your team definition to `hr_team.json` in the current directory using the Write tool.
The file must contain ONLY valid JSON with this schema:

```json
{_HR_SCHEMA}
```

Rules:
- Include a lead and at least one coder or reviewer.
- Roles must be one of: lead, coder, reviewer, tester.
- IDs are snake_case, unique, descriptive (e.g. be_lead, be_coder_1).
- Identity: 2-3 sentences in second person. State specific expertise, approach, and style.
  Good: "You are a senior Go developer who specialises in concurrent systems. You prefer
  table-driven tests and always benchmark before optimising."
  Bad: "You are a software developer who writes code."
- knowledge: at least 3 specific, actionable items per person, relevant to their technology.
  Good: "Use context.Context as the first arg of every function that may block."
  Bad: "Write good code."
- rules: at least 2 behavioral constraints per person. Start with Always, Never, or When.
  Good: "Always validate input at the boundary before passing it deeper."
  Bad: "Be helpful."
"""

_HR_REVIEW_SYSTEM = f"""\
You are an HR Quality Reviewer. You check team definitions for agent quality before they go live.

You will receive a proposed team definition as JSON. Evaluate every person against these criteria:

Identity:
- Must be 2-3 sentences in second person ("You are...")
- Must describe specific expertise, approach, and style — not just a job title
- Must give the agent a clear sense of how to behave

Knowledge:
- Must have at least 3 items per person
- Each item must be specific and actionable — not generic advice
- Items must match the technology context of the team

Rules:
- Must have at least 2 items per person
- Each rule must be a behavioral constraint (starts with Always, Never, When, or similar)
- Not generic values ("Be helpful", "Write good code")

If the definition meets all criteria, write ONLY {{"verdict": "approved"}} to `hr_team_review.json`.

If it has quality issues, fix them and write the corrected team definition to `hr_team_review.json`.
The corrected file must use the same schema:

```json
{_HR_SCHEMA}
```
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


async def _sdk_query(prompt: str, system: str, max_turns: int = 3) -> None:
    """Run a one-shot claude-code-sdk query with bypassPermissions. Side effects via tools."""
    from claude_code_sdk import query, ClaudeCodeOptions

    async for _ in query(
        prompt=prompt,
        options=ClaudeCodeOptions(
            system_prompt=system,
            cwd=str(config.BASE_DIR),
            permission_mode="bypassPermissions",
            max_turns=max_turns,
        ),
    ):
        pass


# ── CTO planning ──────────────────────────────────────────────────────────────

class CTOPlanning:
    async def run(self, requirements_text: str, on_status: callable) -> dict:
        on_status("CTO team is analysing requirements...")
        state_yaml = yaml.dump(registry.load_state().to_dict(), default_flow_style=False)
        team, lead, members, skill_registry = registry.load_team_with_members("cto_team")
        rules = SessionRules.from_dict(team.communication) if team.communication else SessionRules()
        session = create_session("cto_planning", [p.id for p in members], rules)

        plan_file = config.BASE_DIR / "cto_plan.json"
        if plan_file.exists():
            plan_file.unlink()  # remove any leftover from a prior failed run

        await run_pattern(
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

        if not plan_file.exists():
            raise ValueError(
                "CTO did not write cto_plan.json — plan output is missing. "
                "The CTO must use the Write tool to save the plan as JSON."
            )
        try:
            return json.loads(plan_file.read_text(encoding="utf-8"))
        finally:
            plan_file.unlink(missing_ok=True)


# ── HR team creation ──────────────────────────────────────────────────────────

class HRTeamCreation:
    async def run(self, team_id: str, tech_context: str) -> dict:
        from claude_code_sdk import query, ClaudeCodeOptions

        creation_file = config.BASE_DIR / "hr_team.json"
        review_file = config.BASE_DIR / "hr_team_review.json"
        for f in (creation_file, review_file):
            if f.exists():
                f.unlink()

        # Step 1: HR creates the team and writes hr_team.json
        await _sdk_query(
            prompt=(
                f"Create a software engineering team with id='{team_id}'.\n"
                f"Technology context: {tech_context}"
            ),
            system=_HR_SYSTEM,
            max_turns=5,
        )
        if not creation_file.exists():
            raise ValueError(f"HR did not write hr_team.json for team '{team_id}'")
        proposed = json.loads(creation_file.read_text(encoding="utf-8"))

        # Step 2: HR reviewer checks quality; may write corrected version
        await _sdk_query(
            prompt=(
                f"Review this team definition for team '{team_id}':\n\n"
                + json.dumps(proposed, indent=2)
            ),
            system=_HR_REVIEW_SYSTEM,
            max_turns=3,
        )

        result = proposed
        if review_file.exists():
            review_data = json.loads(review_file.read_text(encoding="utf-8"))
            if review_data.get("verdict") != "approved" and "team" in review_data:
                result = review_data

        for f in (creation_file, review_file):
            f.unlink(missing_ok=True)

        return result


_VALID_PERSON_ROLES = {"lead", "coder", "reviewer", "tester"}


def _validate_hr_result(result: dict, team_id: str) -> None:
    """Raise ValueError if HR-produced team data is structurally invalid."""
    team_data = result.get("team", result)
    members = team_data.get("members", [])
    lead_id = team_data.get("lead_id", "")

    if not members:
        raise ValueError(f"HR created team '{team_id}' with no members")
    if lead_id not in members:
        raise ValueError(
            f"HR created team '{team_id}': lead_id '{lead_id}' not in members {members}"
        )

    for person_data in result.get("persons", []):
        pid = person_data.get("id", "<unknown>")
        role = person_data.get("role", "")
        if role not in _VALID_PERSON_ROLES:
            raise ValueError(
                f"HR created person '{pid}' with invalid role '{role}'. "
                f"Valid roles: {sorted(_VALID_PERSON_ROLES)}"
            )
        if not person_data.get("identity", "").strip():
            raise ValueError(f"HR created person '{pid}' with empty identity")


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
        _validate_hr_result(result, team_id)
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

            sub_plan_dict = await CTOPlanning().run(approved_spec, on_status)

            plan_val = PlanValidation()
            approved_sub_plan, _ = await plan_val.run(sub_plan_dict, on_status=on_status)

            # Create any teams the sub-plan needs that don't exist yet
            sub_teams_required = approved_sub_plan.get("teams_required", [])
            sub_tech_stack = approved_sub_plan.get("tech_stack", [])
            if sub_teams_required:
                await _create_missing_teams(sub_teams_required, sub_tech_stack, on_status)

            sub_requirements = [
                Requirement.from_dict(r) for r in approved_sub_plan.get("requirements", [])
            ]
            sub_context = f"Parent task: {title}\n{parent_context}"
            sub_stubs = await _build_task_tree(
                approved_sub_plan.get("tasks", []),
                project_id, sub_requirements,
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
    on_status: callable,
) -> Plan:
    parent_context = _build_parent_context(title, tech_stack, raw_tasks)
    project_root = registry.project_dir(project_id)

    task_stubs = await _build_task_tree(
        raw_tasks=raw_tasks,
        project_id=project_id,
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

    # 2. CTO produces plan (reads fresh state from disk internally)
    plan_dict = await CTOPlanning().run(approved_text, _status)

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
