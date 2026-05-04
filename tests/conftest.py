"""
Shared fixtures for the aicompany test suite.

Every test that touches the filesystem gets an isolated tmp directory so tests
never interfere with each other or the real company/ and projects/ folders.
"""
import pytest
import yaml
from pathlib import Path

import aicompany.config as config
from aicompany.models import CompanyState, Person, ProjectPlan, Skill, Task, Team


# ── Filesystem isolation ───────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_fs(tmp_path, monkeypatch):
    """
    Redirect all config paths to a fresh tmp directory for every test.
    This means no test ever reads or writes to the real company/ or projects/.
    """
    company_dir = tmp_path / "company"
    teams_dir = company_dir / "teams"
    skills_dir = company_dir / "skills"
    projects_dir = tmp_path / "projects"

    company_dir.mkdir()
    teams_dir.mkdir()
    skills_dir.mkdir()
    projects_dir.mkdir()

    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config, "COMPANY_DIR", company_dir)
    monkeypatch.setattr(config, "STATE_FILE", company_dir / "state.yaml")
    monkeypatch.setattr(config, "TEAMS_DIR", teams_dir)
    monkeypatch.setattr(config, "SKILLS_DIR", skills_dir)
    monkeypatch.setattr(config, "PROJECTS_DIR", projects_dir)

    return tmp_path


# ── Reusable model factories ───────────────────────────────────────────────────

@pytest.fixture
def sample_skills() -> list:
    return [
        Skill(id="python", name="Python", category="language",
              knowledge=["Use type hints on all function signatures"]),
        Skill(id="fastapi", name="FastAPI", category="framework",
              knowledge=["Use async def for route handlers"]),
    ]


@pytest.fixture
def sample_persons() -> list:
    return [
        Person(id="be_lead", name="Backend Lead", role="lead",
               identity="You are a backend lead.",
               skills=["python", "fastapi"],
               knowledge=["You coordinate the backend team"],
               rules=["Be concise in briefs"]),
        Person(id="be_coder", name="Backend Coder", role="coder",
               identity="You are a backend coder.",
               skills=["python", "fastapi"],
               knowledge=[],
               rules=["Write complete, runnable code"]),
    ]


@pytest.fixture
def sample_team() -> Team:
    return Team(
        id="backend_engineer",
        name="Backend Engineer",
        skills=["python", "fastapi", "postgresql"],
        members=["be_lead", "be_coder"],
        lead_id="be_lead",
    )


@pytest.fixture
def sample_state(sample_team) -> CompanyState:
    return CompanyState(
        version="1",
        teams=[{"id": sample_team.id, "name": sample_team.name, "skills": sample_team.skills}],
        technologies_seen=["python", "fastapi"],
    )


@pytest.fixture
def sample_tasks() -> list:
    return [
        Task(
            id="task_001",
            title="Design schema",
            description="Create the DB schema",
            assigned_team="backend_engineer",
            depends_on=[],
            is_checkpoint=False,
        ),
        Task(
            id="task_002",
            title="Implement API",
            description="Build REST endpoints",
            assigned_team="backend_engineer",
            depends_on=["task_001"],
            is_checkpoint=True,
        ),
        Task(
            id="task_003",
            title="Write tests",
            description="Unit tests for the API",
            assigned_team="backend_engineer",
            depends_on=["task_002"],
            is_checkpoint=False,
        ),
    ]


@pytest.fixture
def sample_plan(sample_tasks) -> ProjectPlan:
    return ProjectPlan(
        project_id="proj_test01",
        title="Test Project",
        tech_stack=["python", "fastapi"],
        teams_required=["backend_engineer"],
        tasks=sample_tasks,
    )


# ── Helpers ────────────────────────────────────────────────────────────────────

def write_state(state: CompanyState) -> None:
    """Write a CompanyState to the (patched) STATE_FILE."""
    with config.STATE_FILE.open("w") as f:
        yaml.dump(state.to_dict(), f, default_flow_style=False)


def write_team(team: Team) -> None:
    """Write a Team to the (patched) TEAMS_DIR."""
    path = config.TEAMS_DIR / f"{team.id}.yaml"
    with path.open("w") as f:
        yaml.dump(team.to_dict(), f, default_flow_style=False)


def write_persons(persons: list) -> None:
    """Write Person objects to the (patched) company/persons/ dir."""
    persons_dir = config.COMPANY_DIR / "persons"
    persons_dir.mkdir(parents=True, exist_ok=True)
    for p in persons:
        path = persons_dir / f"{p.id}.yaml"
        with path.open("w") as f:
            yaml.dump(p.to_dict(), f, default_flow_style=False)


def write_skills(skills: list) -> None:
    """Write Skill objects to the (patched) company/skills/ dir."""
    skills_dir = config.SKILLS_DIR
    skills_dir.mkdir(parents=True, exist_ok=True)
    for s in skills:
        path = skills_dir / f"{s.id}.yaml"
        with path.open("w") as f:
            yaml.dump(s.to_dict(), f, default_flow_style=False)


def write_plan(plan: ProjectPlan) -> None:
    """Write a ProjectPlan to the (patched) PROJECTS_DIR."""
    proj_dir = config.PROJECTS_DIR / plan.project_id
    (proj_dir / "decisions").mkdir(parents=True, exist_ok=True)
    (proj_dir / "outputs").mkdir(parents=True, exist_ok=True)
    (proj_dir / "requirements.md").write_text("# Test requirements", encoding="utf-8")
    with (proj_dir / "plan.yaml").open("w") as f:
        yaml.dump(plan.to_dict(), f, default_flow_style=False)
