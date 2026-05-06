"""
Input validation for requirements, CTO plans, and HR responses.
"""


# ── Requirements ───────────────────────────────────────────────────────────────

def validate_requirements_text(text: str) -> list[str]:
    """Static checks on a requirements document. Delegates to TaskInput.validate()."""
    from .models import TaskInput
    return TaskInput(specification=text).validate()


# ── CTO plan ───────────────────────────────────────────────────────────────────

def _validate_plan_structure(plan_dict: dict) -> list[str]:
    errors = []
    for key in ("title", "tasks"):
        if key not in plan_dict:
            errors.append(f"CTO plan missing required key: '{key}'")
    if "title" in plan_dict and not plan_dict["title"].strip():
        errors.append("CTO plan has an empty title.")
    tasks = plan_dict.get("tasks", [])
    if not isinstance(tasks, list):
        errors.append("CTO plan 'tasks' is not a list.")
    elif not tasks:
        errors.append("CTO plan has no tasks.")
    return errors


def _validate_tasks(tasks: list) -> list[str]:
    errors = []
    seen_ids: set[str] = set()
    for i, task in enumerate(tasks):
        if not isinstance(task, dict):
            errors.append(f"Task {i} is not a valid object.")
            continue
        for key in ("title", "description", "assigned_team"):
            if not str(task.get(key, "")).strip():
                errors.append(f"Task {i} missing required field: '{key}'")
        task_id = task.get("id", "")
        if task_id:
            if task_id in seen_ids:
                errors.append(f"Duplicate task ID: '{task_id}'")
            seen_ids.add(task_id)
    return errors


def _validate_task_dependencies(tasks: list) -> list[str]:
    all_ids = {t.get("id", f"task_{i+1:03d}") for i, t in enumerate(tasks)}
    return [
        f"Task '{task.get('id', '?')}' depends on unknown task '{dep}'"
        for task in tasks
        for dep in task.get("depends_on", [])
        if dep not in all_ids
    ]


def validate_cto_plan(plan_dict: dict) -> list[str]:
    """Validate the structure of a CTO-generated plan. Returns [] on valid."""
    if not isinstance(plan_dict, dict):
        return ["CTO response is not a valid JSON object."]
    errors = _validate_plan_structure(plan_dict)
    tasks = plan_dict.get("tasks", [])
    if isinstance(tasks, list):
        errors += _validate_tasks(tasks)
        errors += _validate_task_dependencies(tasks)
    return errors


# ── HR response ────────────────────────────────────────────────────────────────

def _validate_team_structure(team_data: dict, team_id: str) -> tuple[list[str], list[str]]:
    """Returns (errors, members)."""
    errors = []
    members = team_data.get("members", [])
    if not members:
        errors.append(f"Team '{team_id}' has no members.")
    lead_id = team_data.get("lead_id", "")
    if not lead_id:
        errors.append(f"Team '{team_id}' has no lead_id.")
    elif lead_id not in members:
        errors.append(f"Team '{team_id}' lead_id '{lead_id}' is not in members list.")
    return errors, members


def _validate_persons(persons_data: list, members: list, team_id: str) -> list[str]:
    errors = []
    person_ids = {p.get("id", "") for p in persons_data if isinstance(p, dict)}
    for mid in members:
        if mid not in person_ids:
            errors.append(f"Team '{team_id}' member '{mid}' has no corresponding person definition.")
    for p in persons_data:
        if not isinstance(p, dict):
            continue
        pid = p.get("id", "unknown")
        if not p.get("identity", "").strip() and not p.get("system_prompt", "").strip():
            errors.append(f"Person '{pid}' has no identity.")
        if not p.get("role", "").strip():
            errors.append(f"Person '{pid}' has no role.")
    return errors


def validate_hr_response(result: dict, team_id: str) -> list[str]:
    """Validate the structure of an HR-created team response. Returns [] on valid."""
    if not isinstance(result, dict):
        return ["HR response is not a valid JSON object."]
    team_data = result.get("team", result)
    if not isinstance(team_data, dict):
        return ["HR response 'team' is not a valid object."]
    errors, members = _validate_team_structure(team_data, team_id)
    errors += _validate_persons(result.get("persons", []), members, team_id)
    return errors
