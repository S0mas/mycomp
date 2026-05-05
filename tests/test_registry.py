"""
Tests for aicompany/registry.py

What we verify:
  - load_state() raises if state.yaml missing
  - save_state() / load_state() round-trip
  - save_team() / load_team() round-trip + auto-syncs state.yaml
  - find_missing_skills() returns only truly absent skills
  - find_team_for_skill() finds correct team or returns None
  - create_project_dir() creates correct subdirectories
  - save_plan() / load_plan() round-trip
  - save_output() / load_output() write and read task output
  - save_decision() creates a markdown file in decisions/
  - list_projects() returns project IDs from projects dir
"""
import pytest
import yaml

import aicompany.config as config
from aicompany import registry
from aicompany.models import CompanyState, ProjectPlan, Skill, Task, Team
from tests.conftest import write_state, write_team, write_plan, write_skills


# ── state ──────────────────────────────────────────────────────────────────────

class TestLoadSaveState:
    def test_load_raises_if_missing(self):
        with pytest.raises(FileNotFoundError, match="initialised"):
            registry.load_state()

    def test_round_trip(self, sample_state):
        registry.save_state(sample_state)
        loaded = registry.load_state()
        assert loaded.version == sample_state.version
        assert loaded.team_ids() == sample_state.team_ids()
        assert loaded.technologies_seen == sample_state.technologies_seen

    def test_save_creates_file(self, sample_state):
        registry.save_state(sample_state)
        assert config.STATE_FILE.exists()


# ── teams ──────────────────────────────────────────────────────────────────────

class TestLoadSaveTeam:
    def test_load_raises_if_missing(self):
        # Need state to exist for save_team to sync
        registry.save_state(CompanyState())
        with pytest.raises(FileNotFoundError):
            registry.load_team("nonexistent")

    def test_round_trip(self, sample_team, sample_state):
        write_state(sample_state)
        registry.save_team(sample_team)
        loaded = registry.load_team(sample_team.id)
        assert loaded.id == sample_team.id
        assert loaded.skills == sample_team.skills
        assert loaded.members == sample_team.members
        assert loaded.lead_id == sample_team.lead_id

    def test_save_team_syncs_state(self, sample_state):
        # Start with a state that has no teams
        empty_state = CompanyState()
        registry.save_state(empty_state)

        new_team = Team(
            id="devops_engineer",
            name="DevOps Engineer",
            skills=["docker", "kubernetes"],
            members=["devops_lead"],
            lead_id="devops_lead",
        )
        registry.save_team(new_team)

        state = registry.load_state()
        assert "devops_engineer" in state.team_ids()

    def test_save_team_does_not_duplicate_in_state(self, sample_team, sample_state):
        write_state(sample_state)
        registry.save_team(sample_team)
        registry.save_team(sample_team)  # second save — should not duplicate
        state = registry.load_state()
        ids = [t["id"] for t in state.teams]
        assert ids.count("backend_engineer") == 1


# ── skills ─────────────────────────────────────────────────────────────────────

class TestLoadSaveSkill:
    def test_load_raises_if_missing(self):
        with pytest.raises(FileNotFoundError):
            registry.load_skill("nonexistent")

    def test_round_trip(self, sample_skills):
        registry.save_state(CompanyState())
        skill = sample_skills[0]
        registry.save_skill(skill)
        loaded = registry.load_skill(skill.id)
        assert loaded.id == skill.id
        assert loaded.name == skill.name
        assert loaded.knowledge == skill.knowledge

    def test_save_skill_syncs_state(self, sample_skills):
        registry.save_state(CompanyState())
        registry.save_skill(sample_skills[0])
        state = registry.load_state()
        assert "python" in state.skill_ids()

    def test_save_skill_does_not_duplicate(self, sample_skills):
        registry.save_state(CompanyState())
        registry.save_skill(sample_skills[0])
        registry.save_skill(sample_skills[0])
        state = registry.load_state()
        assert state.skill_ids().count("python") == 1


class TestFindSkills:
    def test_find_missing_skills_all_present(self, sample_state):
        missing = registry.find_missing_skills(["python", "fastapi"], sample_state)
        assert missing == []

    def test_find_missing_skills_some_missing(self, sample_state):
        missing = registry.find_missing_skills(["python", "kubernetes"], sample_state)
        assert "kubernetes" in missing
        assert "python" not in missing

    def test_find_missing_skills_case_insensitive(self, sample_state):
        missing = registry.find_missing_skills(["Python", "FastAPI"], sample_state)
        assert missing == []

    def test_find_team_for_skill_found(self, sample_state):
        team_id = registry.find_team_for_skill("python", sample_state)
        assert team_id == "backend_engineer"

    def test_find_team_for_skill_not_found(self, sample_state):
        team_id = registry.find_team_for_skill("cobol", sample_state)
        assert team_id is None

    def test_find_team_for_skill_case_insensitive(self, sample_state):
        team_id = registry.find_team_for_skill("Python", sample_state)
        assert team_id == "backend_engineer"


# ── projects ───────────────────────────────────────────────────────────────────

class TestProjectDir:
    def test_create_project_dir_structure(self):
        d = registry.create_project_dir("proj_abc", "# My requirements")
        assert (d / "decisions").is_dir()
        assert (d / "outputs").is_dir()
        assert (d / "requirements.md").read_text() == "# My requirements"

    def test_create_project_dir_returns_path(self):
        path = registry.create_project_dir("proj_xyz", "req")
        assert path == config.PROJECTS_DIR / "proj_xyz"


class TestLoadSavePlan:
    def test_load_raises_if_missing(self):
        with pytest.raises(FileNotFoundError):
            registry.load_plan("proj_ghost")

    def test_round_trip(self, sample_plan):
        write_plan(sample_plan)
        loaded = registry.load_plan(sample_plan.project_id)
        assert loaded.project_id == sample_plan.project_id
        assert loaded.title == sample_plan.title
        assert len(loaded.tasks) == len(sample_plan.tasks)
        assert loaded.tasks[1].is_checkpoint is True

    def test_save_overwrites(self, sample_plan):
        write_plan(sample_plan)
        sample_plan.status = "running"
        registry.save_plan(sample_plan)
        loaded = registry.load_plan(sample_plan.project_id)
        assert loaded.status == "running"


class TestOutputs:
    def test_save_and_load_output(self, sample_plan):
        write_plan(sample_plan)
        rel = registry.save_output(sample_plan.project_id, "task_001", "# Output\nSome code")
        assert rel == "outputs/task_001.md"
        content = registry.load_output(sample_plan.project_id, "task_001")
        assert content == "# Output\nSome code"

    def test_load_output_missing_returns_none(self, sample_plan):
        write_plan(sample_plan)
        assert registry.load_output(sample_plan.project_id, "task_999") is None


class TestDecisions:
    def test_save_decision_creates_file(self, sample_plan):
        write_plan(sample_plan)
        registry.save_decision(sample_plan.project_id, "task_002", {
            "action": "approved",
            "task_title": "Implement API",
            "timestamp": "2026-05-04T10:00:00",
            "modified_instructions": "",
            "user_note": "",
        })
        decisions_dir = config.PROJECTS_DIR / sample_plan.project_id / "decisions"
        files = list(decisions_dir.glob("*.md"))
        assert len(files) == 1
        content = files[0].read_text()
        assert "approved" in content
        assert "task_002" in content


class TestListProjects:
    def test_empty(self):
        assert registry.list_projects() == []

    def test_lists_project_dirs(self, sample_plan):
        write_plan(sample_plan)
        projects = registry.list_projects()
        assert sample_plan.project_id in projects


class TestSessionPersistence:
    def test_save_and_load_session_round_trip(self, isolated_fs):
        from aicompany.models import Message, Session, SessionRules
        session = Session(
            id="sess_abc", task_id="task_001", participants=["alice", "bob"],
            rules=SessionRules(pattern="lead_delegates", max_rounds=3),
        )
        session.messages.append(
            Message(sender="alice", recipient="bob", kind="brief", content="Do the thing")
        )
        session.round = 1
        session.status = "complete"

        (config.PROJECTS_DIR / "proj_test").mkdir(parents=True, exist_ok=True)
        registry.save_session("proj_test", session)

        loaded = registry.load_session("proj_test", "task_001")
        assert loaded is not None
        assert loaded.id == "sess_abc"
        assert loaded.task_id == "task_001"
        assert loaded.round == 1
        assert loaded.status == "complete"
        assert len(loaded.messages) == 1
        assert loaded.messages[0].content == "Do the thing"
        assert loaded.rules.pattern == "lead_delegates"

    def test_load_session_returns_none_if_missing(self, isolated_fs):
        assert registry.load_session("proj_nonexistent", "task_001") is None

    def test_save_session_creates_sessions_dir(self, isolated_fs):
        from aicompany.models import Session
        session = Session(id="s", task_id="t1", participants=[])
        (config.PROJECTS_DIR / "proj_x").mkdir(parents=True, exist_ok=True)
        registry.save_session("proj_x", session)
        assert (config.PROJECTS_DIR / "proj_x" / "sessions" / "t1.json").exists()


class TestMaterializeFiles:
    def test_writes_file_from_tag(self, tmp_path):
        text = '<write_file path="app/main.py">\nprint("hello")\n</write_file>'
        written = registry.materialize_files(text, tmp_path)
        assert written == ["app/main.py"]
        assert (tmp_path / "app/main.py").read_text() == 'print("hello")'

    def test_creates_parent_dirs(self, tmp_path):
        text = '<write_file path="a/b/c.py">\nx = 1\n</write_file>'
        registry.materialize_files(text, tmp_path)
        assert (tmp_path / "a/b/c.py").exists()

    def test_blocks_path_traversal(self, tmp_path):
        text = '<write_file path="../evil.py">\nbad\n</write_file>'
        written = registry.materialize_files(text, tmp_path)
        assert written == []
        assert not (tmp_path.parent / "evil.py").exists()

    def test_returns_empty_for_no_tags(self, tmp_path):
        assert registry.materialize_files("no tags here", tmp_path) == []

    def test_multiple_files(self, tmp_path):
        text = (
            '<write_file path="a.py">\nx\n</write_file>\n'
            '<write_file path="b.py">\ny\n</write_file>'
        )
        written = registry.materialize_files(text, tmp_path)
        assert set(written) == {"a.py", "b.py"}
        assert (tmp_path / "a.py").exists()
        assert (tmp_path / "b.py").exists()
