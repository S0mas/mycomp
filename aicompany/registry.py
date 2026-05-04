from pathlib import Path

import yaml

from . import config
from .models import CompanyState, Person, ProjectPlan, Skill, Task, Team


# ── Company state ──────────────────────────────────────────────────────────────

def load_state() -> CompanyState:
    if not config.STATE_FILE.exists():
        raise FileNotFoundError(
            "Company not initialised. Run: python main.py init"
        )
    with config.STATE_FILE.open() as f:
        return CompanyState.from_dict(yaml.safe_load(f))


def save_state(state: CompanyState) -> None:
    config.COMPANY_DIR.mkdir(parents=True, exist_ok=True)
    with config.STATE_FILE.open("w") as f:
        yaml.dump(state.to_dict(), f, default_flow_style=False, allow_unicode=True)


# ── Persons ────────────────────────────────────────────────────────────────────

def _persons_dir() -> Path:
    return config.COMPANY_DIR / "persons"


def load_person(person_id: str) -> Person:
    path = _persons_dir() / f"{person_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Person file not found: {path}")
    with path.open() as f:
        return Person.from_dict(yaml.safe_load(f))


def save_person(person: Person) -> None:
    """
    Persist a Person to disk and register it in state.yaml.

    Side effect: if this person ID is new, it is appended to state.yaml's
    persons list. This keeps the central registry in sync automatically.
    """
    _persons_dir().mkdir(parents=True, exist_ok=True)
    path = _persons_dir() / f"{person.id}.yaml"
    with path.open("w") as f:
        yaml.dump(person.to_dict(), f, default_flow_style=False, allow_unicode=True)

    # Keep state.yaml in sync
    state = load_state()
    person_entry = {"id": person.id, "name": person.name, "role": person.role}
    if person.id not in state.person_ids():
        state.persons.append(person_entry)
        save_state(state)


# ── Skills ─────────────────────────────────────────────────────────────────────

def load_skill(skill_id: str) -> Skill:
    path = config.SKILLS_DIR / f"{skill_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Skill file not found: {path}")
    with path.open() as f:
        return Skill.from_dict(yaml.safe_load(f))


def save_skill(skill: Skill) -> None:
    """
    Persist a Skill to disk and register it in state.yaml.

    Side effect: if this skill ID is new, it is appended to state.yaml's
    skills list. This keeps the central registry in sync automatically.
    """
    config.SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    path = config.SKILLS_DIR / f"{skill.id}.yaml"
    with path.open("w") as f:
        yaml.dump(skill.to_dict(), f, default_flow_style=False, allow_unicode=True)

    # Keep state.yaml in sync
    state = load_state()
    skill_entry = {"id": skill.id, "name": skill.name, "category": skill.category}
    if skill.id not in state.skill_ids():
        state.skills.append(skill_entry)
        save_state(state)


# ── Teams ──────────────────────────────────────────────────────────────────────

def load_team(team_id: str) -> Team:
    path = config.TEAMS_DIR / f"{team_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Team file not found: {path}")
    with path.open() as f:
        return Team.from_dict(yaml.safe_load(f))


def load_team_with_members(team_id: str) -> tuple[Team, Person, list[Person], dict]:
    """Return (team, lead_person, [all_member_persons], {skill_id: Skill})."""
    team = load_team(team_id)
    members = [load_person(pid) for pid in team.members]
    lead = next((p for p in members if p.id == team.lead_id), members[0])

    # Collect all unique skill IDs referenced by team members
    skill_ids = set()
    for p in members:
        skill_ids.update(p.skills)

    skill_registry = {}
    for sid in skill_ids:
        try:
            skill_registry[sid] = load_skill(sid)
        except FileNotFoundError:
            pass  # skill file missing — skip gracefully

    return team, lead, members, skill_registry


def save_team(team: Team) -> None:
    """
    Persist a Team to disk and register it in state.yaml.

    Side effect: if this team ID is new, it is appended to state.yaml's
    teams list. This keeps the central registry in sync automatically.
    """
    config.TEAMS_DIR.mkdir(parents=True, exist_ok=True)
    path = config.TEAMS_DIR / f"{team.id}.yaml"
    with path.open("w") as f:
        yaml.dump(team.to_dict(), f, default_flow_style=False, allow_unicode=True)

    # Keep state.yaml in sync
    state = load_state()
    team_entry = {"id": team.id, "name": team.name, "skills": team.skills}
    if team.id not in state.team_ids():
        state.teams.append(team_entry)
        save_state(state)


def find_missing_skills(required: list, state: CompanyState) -> list:
    available = state.all_skills()
    return [s for s in required if s.lower() not in available]


def find_team_for_skill(skill: str, state: CompanyState) -> str | None:
    skill = skill.lower()
    for team_entry in state.teams:
        if skill in {s.lower() for s in team_entry.get("skills", [])}:
            return team_entry["id"]
    return None


# ── Projects ───────────────────────────────────────────────────────────────────

def project_dir(project_id: str) -> Path:
    return config.PROJECTS_DIR / project_id


def create_project_dir(project_id: str, requirements_text: str) -> Path:
    d = project_dir(project_id)
    (d / "decisions").mkdir(parents=True, exist_ok=True)
    (d / "outputs").mkdir(parents=True, exist_ok=True)
    (d / "requirements.md").write_text(requirements_text, encoding="utf-8")
    return d


def load_plan(project_id: str) -> ProjectPlan:
    path = project_dir(project_id) / "plan.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Plan not found for project: {project_id}")
    with path.open() as f:
        return ProjectPlan.from_dict(yaml.safe_load(f))


def save_plan(plan: ProjectPlan) -> None:
    path = project_dir(plan.project_id) / "plan.yaml"
    with path.open("w") as f:
        yaml.dump(plan.to_dict(), f, default_flow_style=False, allow_unicode=True)


def save_output(project_id: str, task_id: str, content: str) -> str:
    filename = f"{task_id}.md"
    path = project_dir(project_id) / "outputs" / filename
    path.write_text(content, encoding="utf-8")
    return str(path.relative_to(project_dir(project_id)))


def load_output(project_id: str, task_id: str) -> str | None:
    path = project_dir(project_id) / "outputs" / f"{task_id}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def save_decision(project_id: str, task_id: str, record: dict) -> None:
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    filename = f"{ts}_{task_id}.md"
    path = project_dir(project_id) / "decisions" / filename

    lines = [
        f"# Decision: {record.get('action', '').capitalize()} — {record.get('task_title', task_id)}",
        "",
        f"**Timestamp**: {record.get('timestamp', ts)}",
        f"**Project**: {project_id}",
        f"**Task**: {task_id}",
        f"**Action**: {record.get('action', '')}",
        "",
    ]
    if record.get("user_note"):
        lines += [f"**User note**: {record['user_note']}", ""]
    if record.get("modified_instructions"):
        lines += ["## Modified instructions", "", record["modified_instructions"], ""]

    path.write_text("\n".join(lines), encoding="utf-8")


def list_projects() -> list:
    if not config.PROJECTS_DIR.exists():
        return []
    return [p.name for p in sorted(config.PROJECTS_DIR.iterdir()) if p.is_dir()]
