import warnings
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import config
from .models import (
    CompanyState, Person, Plan, Requirement, RequirementTest,
    Skill, TaskInput, Team, RequirementTestSuite,
)


# ── YAML I/O helpers ───────────────────────────────────────────────────────────

def _load_yaml(path: Path, model_class):
    with path.open(encoding="utf-8") as f:
        return model_class.from_dict(yaml.safe_load(f))


def _save_yaml(path: Path, obj) -> None:
    with path.open("w", encoding="utf-8") as f:
        yaml.dump(obj.to_dict(), f, default_flow_style=False, allow_unicode=True)


# ── Company state ──────────────────────────────────────────────────────────────

def load_state() -> CompanyState:
    if not config.STATE_FILE.exists():
        raise FileNotFoundError(
            "Company not initialised. Run: python main.py init"
        )
    return _load_yaml(config.STATE_FILE, CompanyState)


def save_state(state: CompanyState) -> None:
    config.COMPANY_DIR.mkdir(parents=True, exist_ok=True)
    _save_yaml(config.STATE_FILE, state)


# ── Persons ────────────────────────────────────────────────────────────────────

def _persons_dir() -> Path:
    return config.COMPANY_DIR / "persons"


def load_person(person_id: str) -> Person:
    path = _persons_dir() / f"{person_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Person file not found: {path}")
    return _load_yaml(path, Person)


def save_person(person: Person) -> None:
    """Persist a Person and auto-register in state.yaml."""
    _persons_dir().mkdir(parents=True, exist_ok=True)
    _save_yaml(_persons_dir() / f"{person.id}.yaml", person)
    state = load_state()
    if person.id not in state.person_ids():
        state.persons.append({"id": person.id, "name": person.name, "role": person.role})
        save_state(state)


# ── Skills ─────────────────────────────────────────────────────────────────────

def load_skill(skill_id: str) -> Skill:
    path = config.SKILLS_DIR / f"{skill_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Skill file not found: {path}")
    return _load_yaml(path, Skill)


def save_skill(skill: Skill) -> None:
    """Persist a Skill and auto-register in state.yaml."""
    config.SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    _save_yaml(config.SKILLS_DIR / f"{skill.id}.yaml", skill)
    state = load_state()
    if skill.id not in state.skill_ids():
        state.skills.append({"id": skill.id, "name": skill.name, "category": skill.category})
        save_state(state)


# ── Teams ──────────────────────────────────────────────────────────────────────

def load_team(team_id: str) -> Team:
    path = config.TEAMS_DIR / f"{team_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Team file not found: {path}")
    return _load_yaml(path, Team)


def load_team_with_members(team_id: str) -> tuple[Team, Person, list[Person], dict]:
    """Return (team, lead_person, [all_member_persons], {skill_id: Skill})."""
    team = load_team(team_id)
    members = [load_person(pid) for pid in team.members]
    lead = next((p for p in members if p.id == team.lead_id), members[0])

    skill_ids = {sid for p in members for sid in p.skills}
    skill_registry = {}
    for sid in skill_ids:
        try:
            skill_registry[sid] = load_skill(sid)
        except FileNotFoundError:
            pass

    return team, lead, members, skill_registry


def save_team(team: Team) -> None:
    """Persist a Team and auto-register in state.yaml."""
    config.TEAMS_DIR.mkdir(parents=True, exist_ok=True)
    _save_yaml(config.TEAMS_DIR / f"{team.id}.yaml", team)
    state = load_state()
    if team.id not in state.team_ids():
        state.teams.append({"id": team.id, "name": team.name, "skills": team.skills})
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
    for subdir in ("decisions", "outputs", "sessions", "logs", "req_tests", "test_suites"):
        (d / subdir).mkdir(parents=True, exist_ok=True)
    (d / "requirements.md").write_text(requirements_text, encoding="utf-8")
    return d


def append_task_log(project_id: str, task_id: str, level: str, message: str) -> None:
    """Append a timestamped single-line entry to the per-task log file."""
    path = project_dir(project_id) / "logs" / f"{task_id}.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    single_line = message.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    with path.open("a", encoding="utf-8") as f:
        f.write(f"{ts} [{level}] {single_line}\n")


def load_plan(project_id: str) -> Plan:
    path = project_dir(project_id) / "plan.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Plan not found for project: {project_id}")
    plan = _load_yaml(path, Plan)
    # Backward compat: old plan.yaml has no "input" key — inject from requirements.md
    if not plan.input.specification:
        req_path = project_dir(project_id) / "requirements.md"
        if req_path.exists():
            warnings.warn(
                f"Plan '{project_id}' is missing the 'input' field — injecting from "
                "requirements.md (old format). Re-save the plan to migrate.",
                UserWarning,
                stacklevel=2,
            )
            plan.input = TaskInput(specification=req_path.read_text(encoding="utf-8"))
    return plan


def save_plan(plan: Plan) -> None:
    _save_yaml(project_dir(plan.project_id) / "plan.yaml", plan)


def save_output(project_id: str, task_id: str, content: str) -> str:
    path = project_dir(project_id) / "outputs" / f"{task_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path.relative_to(project_dir(project_id)))


def load_output(project_id: str, task_id: str) -> str | None:
    path = project_dir(project_id) / "outputs" / f"{task_id}.md"
    return path.read_text(encoding="utf-8") if path.exists() else None


def materialize_files(text: str, workspace: Path) -> list[str]:
    """Parse <write_file path="..."> blocks from agent output and write to workspace."""
    import re
    pattern = re.compile(
        r'<write_file\s+path=["\']([^"\']+)["\']>(.*?)</write_file>',
        re.DOTALL,
    )
    written = []
    for rel_path, content in pattern.findall(text):
        dest = (workspace / rel_path).resolve()
        if not str(dest).startswith(str(workspace.resolve())):
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content.strip("\n"), encoding="utf-8")
        written.append(rel_path)
    return written


def save_session(project_id: str, session) -> str:
    """Persist a Session's full message log as JSON. Returns relative path."""
    import json
    path = project_dir(project_id) / "sessions" / f"{session.task_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(session.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return str(path.relative_to(project_dir(project_id)))


def load_session(project_id: str, task_id: str):
    """Load a persisted Session. Returns None if not found."""
    import json
    from .models import Session
    path = project_dir(project_id) / "sessions" / f"{task_id}.json"
    if not path.exists():
        return None
    return Session.from_dict(json.loads(path.read_text(encoding="utf-8")))


def save_decision(project_id: str, task_id: str, record: dict) -> None:
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
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
    path = project_dir(project_id) / "decisions" / f"{ts}_{task_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


# ── Requirements & test suites ─────────────────────────────────────────────────

def save_requirements(project_id: str, requirements: list[Requirement]) -> None:
    path = project_dir(project_id) / "req_tests" / "_requirements.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.dump([r.to_dict() for r in requirements], f,
                  default_flow_style=False, allow_unicode=True)


def load_requirements(project_id: str) -> list[Requirement]:
    path = project_dir(project_id) / "req_tests" / "_requirements.yaml"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [Requirement.from_dict(r) for r in (yaml.safe_load(f) or [])]


def save_test_suite(project_id: str, suite: RequirementTestSuite) -> None:
    path = project_dir(project_id) / "test_suites" / f"{suite.id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    _save_yaml(path, suite)


def load_test_suite(project_id: str, suite_id: str) -> RequirementTestSuite:
    path = project_dir(project_id) / "test_suites" / f"{suite_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"RequirementTestSuite not found: {suite_id}")
    return _load_yaml(path, RequirementTestSuite)


def save_requirement_test(project_id: str, req_test: RequirementTest) -> None:
    path = project_dir(project_id) / "req_tests" / f"{req_test.id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    _save_yaml(path, req_test)


def list_projects() -> list:
    if not config.PROJECTS_DIR.exists():
        return []
    return [p.name for p in sorted(config.PROJECTS_DIR.iterdir()) if p.is_dir()]
