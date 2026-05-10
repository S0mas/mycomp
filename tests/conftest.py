"""
Shared fixtures for the aicompany test suite.

Every test that touches the filesystem gets an isolated tmp directory so tests
never interfere with each other or the real company/ and projects/ folders.
"""
import pytest
import yaml
from pathlib import Path

import aicompany.config as config
from aicompany.models import (
    CompanyState, Person, Plan, ProjectPlan, Skill, TaskInput, TaskStub, Team,
)


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
    monkeypatch.setattr(config, "REQUIREMENTS_POLICY_FILE",
                        company_dir / "requirements_policy.md")
    monkeypatch.setattr(config, "PLAN_POLICY_FILE",
                        company_dir / "plan_policy.md")

    return tmp_path


# ── Test helpers ───────────────────────────────────────────────────────────────

def make_task_input(spec: str = "Do something", context: str = "") -> TaskInput:
    """Minimal TaskInput for use in tests."""
    return TaskInput(specification=spec, context=context)


def make_leaf_plan(title: str = "", spec: str = "", plan_id: str = "", requirements: list | None = None) -> Plan:
    """Minimal leaf Plan (no subtasks) for use in tests."""
    return Plan(
        id=plan_id,
        title=title or "leaf plan",
        input=TaskInput(specification=spec),
        requirements=requirements or [],
        tasks=[],
    )


def make_stub(
    task_id: str,
    title: str = "",
    team: str = "backend_engineer",
    depends_on: list | None = None,
    depended_on_by: list | None = None,
    is_checkpoint: bool = False,
    status: str = "pending",
    output_file: str = "",
) -> TaskStub:
    """Minimal TaskStub for use in tests."""
    return TaskStub(
        id=task_id,
        title=title or task_id,
        assigned_team=team,
        depends_on=depends_on or [],
        depended_on_by=depended_on_by or [],
        is_checkpoint=is_checkpoint,
        status=status,
        output_file=output_file,
    )


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
def sample_stubs() -> list:
    return [
        make_stub("task_001", "Design schema",   depends_on=[]),
        make_stub("task_002", "Implement API",   depends_on=["task_001"], is_checkpoint=True),
        make_stub("task_003", "Write tests",     depends_on=["task_002"]),
    ]


# Keep sample_tasks as alias so existing test code still works
@pytest.fixture
def sample_tasks(sample_stubs) -> list:
    return sample_stubs


@pytest.fixture
def sample_plan(sample_stubs) -> Plan:
    # Also compute depended_on_by
    id_map = {s.id: s for s in sample_stubs}
    for s in sample_stubs:
        for dep_id in s.depends_on:
            if dep_id in id_map:
                id_map[dep_id].depended_on_by.append(s.id)
    return Plan(
        id="proj_test01",
        title="Test Project",
        input=TaskInput(specification="# Test requirements"),
        tech_stack=["python", "fastapi"],
        teams_required=["backend_engineer"],
        tasks=sample_stubs,
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


def write_plan(plan: Plan) -> None:
    """Write a Plan and minimal leaf task plans to the (patched) PROJECTS_DIR."""
    proj_dir = config.PROJECTS_DIR / plan.id
    for subdir in ("decisions", "outputs", "sessions", "logs", "req_tests", "test_suites", "tasks"):
        (proj_dir / subdir).mkdir(parents=True, exist_ok=True)
    (proj_dir / "requirements.md").write_text("# Test requirements", encoding="utf-8")
    with (proj_dir / "plan.yaml").open("w") as f:
        yaml.dump(plan.to_dict(), f, default_flow_style=False)
    # Write a minimal leaf plan for each stub so the orchestrator can load them
    for stub in plan.tasks:
        _write_leaf_task_plan(proj_dir, stub.id)


def _write_leaf_task_plan(parent_dir: Path, task_id: str) -> None:
    """Write a minimal leaf plan.yaml for a task under parent_dir/tasks/{task_id}/."""
    task_node = parent_dir / "tasks" / task_id
    task_node.mkdir(parents=True, exist_ok=True)
    leaf = make_leaf_plan(title=f"{task_id} plan", spec=f"Implement {task_id}", plan_id=task_id)
    with (task_node / "plan.yaml").open("w") as f:
        yaml.dump(leaf.to_dict(), f, default_flow_style=False)


def write_task_plan(project_id: str, task_id: str, plan: Plan,
                    parent_dir: Path | None = None) -> None:
    """Write a task's plan to the task tree under the project directory."""
    base = parent_dir or (config.PROJECTS_DIR / project_id)
    task_node = base / "tasks" / task_id
    task_node.mkdir(parents=True, exist_ok=True)
    with (task_node / "plan.yaml").open("w") as f:
        yaml.dump(plan.to_dict(), f, default_flow_style=False)
    # Recursively write leaf plans for any subtask stubs
    for stub in plan.tasks:
        _write_leaf_task_plan(task_node, stub.id)
