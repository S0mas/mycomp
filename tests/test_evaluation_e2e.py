"""
End-to-end evaluation gate tests with realistic requirements documents.
Tests the full flow: sanity checks → evaluation → block/pass → autofix.
"""
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from aicompany import config, registry
from aicompany.cli import cli
from aicompany.validation import validate_requirements_text


# ── Sample requirements at different quality levels ────────────────────────────

TERRIBLE_REQUIREMENTS = "make me an app"

BAD_REQUIREMENTS = """\
I want a website that does stuff with users and data.
It should be fast and look good. Also mobile.
"""

MEDIOCRE_REQUIREMENTS = """\
# Task Manager API

Build a REST API for managing tasks. Users should be able to create, read,
update and delete tasks. Tasks have a title, description and status.
Use Python.
"""

GOOD_REQUIREMENTS = """\
# Task Manager API

## Overview
Build a RESTful API for managing personal tasks, deployed as a Docker container.

## Features
1. **User registration & login** — email/password, JWT tokens, refresh flow
2. **CRUD tasks** — each task has: title (str, required), description (text, optional),
   status (enum: todo/in_progress/done), due_date (datetime, optional), priority (1-5)
3. **List tasks** — paginated, filterable by status and priority, sortable by due_date
4. **Assign labels** — many-to-many relationship, CRUD on labels

## Technical Constraints
- Python 3.11+, FastAPI, SQLAlchemy 2.0, PostgreSQL 15
- Alembic for migrations
- pytest with >80% coverage
- OpenAPI docs auto-generated

## Acceptance Criteria
- All endpoints return proper HTTP status codes (201 for create, 404 for not found, etc.)
- Auth endpoints rate-limited to 5 req/min
- Response time < 200ms for list endpoints (100 items)
- Passwords hashed with bcrypt, never stored in plain text
"""


# ── Sanity check tests (no LLM needed) ────────────────────────────────────────

class TestSanityChecks:
    def test_terrible_too_short(self):
        errors = validate_requirements_text(TERRIBLE_REQUIREMENTS)
        assert any("too short" in e for e in errors)

    def test_bad_too_short(self):
        errors = validate_requirements_text(BAD_REQUIREMENTS)
        # 89 chars — passes the 50-char minimum
        assert errors == []

    def test_mediocre_passes_sanity(self):
        assert validate_requirements_text(MEDIOCRE_REQUIREMENTS) == []

    def test_good_passes_sanity(self):
        assert validate_requirements_text(GOOD_REQUIREMENTS) == []


# ── Full flow tests (mocked LLM) ──────────────────────────────────────────────

@pytest.fixture
def runner(isolated_fs):
    return CliRunner()


def _write_requirements(text: str) -> str:
    import os
    path = os.path.join(os.getcwd(), "reqs.md")
    with open(path, "w") as f:
        f.write(text)
    return path


MOCK_CTO_RESPONSE = {
    "title": "Task Manager", "tech_stack": ["python", "fastapi"],
    "teams_required": ["backend_team"],
    "requirements": [],
    "tasks": [{"id": "t1", "title": "Build API", "description": "d",
               "assigned_team": "backend_team", "depends_on": [], "is_checkpoint": False,
               "requirement_ids": []}],
}

EVAL_PASS = {
    "clarity": 5, "completeness": 4, "feasibility": 5,
    "risks": [], "suggestions": [], "summary": "Excellent requirements.", "verdict": "proceed",
}
EVAL_MEDIOCRE = {
    "clarity": 3, "completeness": 2, "feasibility": 4,
    "risks": ["No auth requirements", "No error handling spec"],
    "suggestions": ["Add acceptance criteria", "Specify database"],
    "summary": "Needs more detail.", "verdict": "needs_work",
}
EVAL_TERRIBLE = {
    "clarity": 1, "completeness": 1, "feasibility": 2,
    "risks": ["Completely undefined scope", "No technical direction"],
    "suggestions": ["Start over with a proper requirements document"],
    "summary": "Not actionable.", "verdict": "reject",
}

MOCK_TEAM_RESPONSE = {
    "team": {"id": "backend_team", "name": "Backend", "skills": [],
             "members": ["be_lead"], "lead_id": "be_lead"},
    "persons": [{"id": "be_lead", "name": "Lead", "role": "lead",
                 "identity": "You are a lead.", "skills": [], "knowledge": [], "rules": []}],
    "skills": [],
}


class TestEvaluationGate:
    def test_good_requirements_proceed(self, runner):
        runner.invoke(cli, ["init"])
        path = _write_requirements(GOOD_REQUIREMENTS)
        with patch("aicompany.planning._run_cto_planning", return_value=MOCK_CTO_RESPONSE), \
             patch("aicompany.evaluation.llm") as m_eval, \
             patch("aicompany.planning.llm") as m_plan:
            m_eval.evaluate_requirements.return_value = EVAL_PASS
            m_plan.hr_create_team.return_value = MOCK_TEAM_RESPONSE
            result = runner.invoke(cli, ["new-project", path])
        assert result.exit_code == 0
        assert "passed evaluation" in result.output

    def test_mediocre_requirements_blocked(self, runner):
        runner.invoke(cli, ["init"])
        path = _write_requirements(MEDIOCRE_REQUIREMENTS)
        with patch("aicompany.planning._run_cto_planning") as mock_cto, \
             patch("aicompany.evaluation.llm") as m:
            m.evaluate_requirements.return_value = EVAL_MEDIOCRE
            result = runner.invoke(cli, ["new-project", path], input="n\n")
        assert result.exit_code == 1
        assert "Cannot proceed" in result.output
        assert "Completeness" in result.output
        mock_cto.assert_not_called()

    def test_terrible_requirements_blocked_with_reject(self, runner):
        runner.invoke(cli, ["init"])
        path = _write_requirements(BAD_REQUIREMENTS)
        with patch("aicompany.planning._run_cto_planning") as mock_cto, \
             patch("aicompany.evaluation.llm") as m:
            m.evaluate_requirements.return_value = EVAL_TERRIBLE
            result = runner.invoke(cli, ["new-project", path], input="n\n")
        assert result.exit_code == 1
        assert "REJECT" in result.output
        assert "Completely undefined scope" in result.output
        mock_cto.assert_not_called()

    def test_terrible_requirements_sanity_blocked(self, runner):
        """Requirements too short — blocked before even calling the LLM."""
        runner.invoke(cli, ["init"])
        path = _write_requirements(TERRIBLE_REQUIREMENTS)
        with patch("aicompany.evaluation.llm") as m:
            result = runner.invoke(cli, ["new-project", path])
        assert result.exit_code == 1
        assert "too short" in result.output
        m.evaluate_requirements.assert_not_called()

    def test_autofix_generates_improved_file(self, runner):
        runner.invoke(cli, ["init"])
        path = _write_requirements(MEDIOCRE_REQUIREMENTS)
        with patch("aicompany.evaluation.llm") as m:
            m.evaluate_requirements.return_value = EVAL_MEDIOCRE
            m.autofix_requirements.return_value = GOOD_REQUIREMENTS
            result = runner.invoke(cli, ["new-project", path], input="y\n")
        assert result.exit_code == 1  # still blocked — user must re-run
        assert "Improved requirements saved" in result.output
        m.autofix_requirements.assert_called_once()
        import os
        fixed_path = path.replace(".md", "_fixed.md")
        assert os.path.exists(fixed_path)
        with open(fixed_path) as f:
            assert "Acceptance Criteria" in f.read()

    def test_fix_guidance_shown(self, runner):
        """Blocked output includes actionable fix hints."""
        runner.invoke(cli, ["init"])
        path = _write_requirements(BAD_REQUIREMENTS)
        with patch("aicompany.evaluation.llm") as m:
            m.evaluate_requirements.return_value = EVAL_MEDIOCRE
            result = runner.invoke(cli, ["new-project", path], input="n\n")
        assert "acceptance criteria" in result.output.lower() or "Add missing sections" in result.output
