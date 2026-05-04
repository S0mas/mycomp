"""
Input validation for requirements, CTO plans, and HR responses.

Provides both static checks (structure, types, sanity) and the
interactive evaluation flow for requirements documents.
"""
from . import config


class ValidationError(Exception):
    """Raised when input fails validation."""
    pass


# ── Requirements ───────────────────────────────────────────────────────────────

def validate_requirements_text(text: str) -> list[str]:
    """
    Run static checks on a requirements document.
    Returns a list of error messages. Empty list = valid.
    """
    errors = []

    if not text or not text.strip():
        errors.append("Requirements file is empty.")
        return errors

    stripped = text.strip()

    if len(stripped) < config.MIN_REQUIREMENTS_LENGTH:
        errors.append(
            f"Requirements too short ({len(stripped)} chars). "
            f"Minimum {config.MIN_REQUIREMENTS_LENGTH} characters needed for meaningful input."
        )

    # Detect binary / non-text content
    try:
        stripped.encode("utf-8")
    except UnicodeEncodeError:
        errors.append("File contains non-text content. Please provide a Markdown or plain text file.")
        return errors

    null_count = stripped.count("\x00")
    if null_count > 0:
        errors.append("File appears to be binary (contains null bytes). Please provide a text file.")

    return errors


# ── CTO plan ───────────────────────────────────────────────────────────────────

def validate_cto_plan(plan_dict: dict) -> list[str]:
    """
    Validate the structure of a CTO-generated plan.
    Returns a list of error messages. Empty list = valid.
    """
    errors = []

    if not isinstance(plan_dict, dict):
        errors.append("CTO response is not a valid JSON object.")
        return errors

    # Required top-level keys
    for key in ("title", "tasks"):
        if key not in plan_dict:
            errors.append(f"CTO plan missing required key: '{key}'")

    if "title" in plan_dict and not plan_dict["title"].strip():
        errors.append("CTO plan has an empty title.")

    tasks = plan_dict.get("tasks", [])
    if not isinstance(tasks, list):
        errors.append("CTO plan 'tasks' is not a list.")
        return errors

    if len(tasks) == 0:
        errors.append("CTO plan has no tasks.")

    # Validate each task
    task_ids = set()
    for i, task in enumerate(tasks):
        if not isinstance(task, dict):
            errors.append(f"Task {i} is not a valid object.")
            continue

        for key in ("title", "description", "assigned_team"):
            if key not in task or not str(task.get(key, "")).strip():
                errors.append(f"Task {i} missing required field: '{key}'")

        task_id = task.get("id", "")
        if task_id:
            if task_id in task_ids:
                errors.append(f"Duplicate task ID: '{task_id}'")
            task_ids.add(task_id)

        # Check depends_on references
        for dep in task.get("depends_on", []):
            if dep not in task_ids and dep not in {t.get("id", "") for t in tasks}:
                # Allow forward references within the same plan
                pass

    # Check all depends_on references resolve
    all_ids = {t.get("id", f"task_{i+1:03d}") for i, t in enumerate(tasks)}
    for task in tasks:
        for dep in task.get("depends_on", []):
            if dep not in all_ids:
                errors.append(f"Task '{task.get('id', '?')}' depends on unknown task '{dep}'")

    return errors


# ── HR response ────────────────────────────────────────────────────────────────

def validate_hr_response(result: dict, team_id: str) -> list[str]:
    """
    Validate the structure of an HR-created team response.
    Returns a list of error messages. Empty list = valid.
    """
    errors = []

    if not isinstance(result, dict):
        errors.append("HR response is not a valid JSON object.")
        return errors

    team_data = result.get("team", result)
    persons_data = result.get("persons", [])

    if not isinstance(team_data, dict):
        errors.append("HR response 'team' is not a valid object.")
        return errors

    # Team must have members
    members = team_data.get("members", [])
    if not members:
        errors.append(f"Team '{team_id}' has no members.")

    # Team must have a lead
    lead_id = team_data.get("lead_id", "")
    if not lead_id:
        errors.append(f"Team '{team_id}' has no lead_id.")
    elif lead_id not in members:
        errors.append(f"Team '{team_id}' lead_id '{lead_id}' is not in members list.")

    # Persons must exist for all members
    person_ids = {p.get("id", "") for p in persons_data if isinstance(p, dict)}
    for mid in members:
        if mid not in person_ids:
            errors.append(f"Team '{team_id}' member '{mid}' has no corresponding person definition.")

    # Each person must have identity
    for p in persons_data:
        if not isinstance(p, dict):
            continue
        pid = p.get("id", "unknown")
        if not p.get("identity", "").strip() and not p.get("system_prompt", "").strip():
            errors.append(f"Person '{pid}' has no identity.")
        if not p.get("role", "").strip():
            errors.append(f"Person '{pid}' has no role.")

    return errors
