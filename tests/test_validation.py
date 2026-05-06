"""Tests for the validation module."""
import pytest

from aicompany.validation import (
    validate_requirements_text,
    validate_cto_plan,
    validate_hr_response,
)


class TestValidateRequirementsText:
    def test_empty_string(self):
        errors = validate_requirements_text("")
        assert len(errors) == 1
        assert "empty" in errors[0].lower()

    def test_whitespace_only(self):
        errors = validate_requirements_text("   \n  ")
        assert len(errors) == 1
        assert "empty" in errors[0].lower()

    def test_too_short(self):
        errors = validate_requirements_text("hello")
        assert any("too short" in e for e in errors)

    def test_null_bytes(self):
        errors = validate_requirements_text("a" * 60 + "\x00")
        assert any("binary" in e for e in errors)

    def test_valid(self):
        assert validate_requirements_text("Build a REST API with user auth and CRUD endpoints.") == []


class TestValidateCTOPlan:
    def test_not_a_dict(self):
        assert validate_cto_plan("bad") != []

    def test_missing_keys(self):
        errors = validate_cto_plan({})
        assert any("title" in e for e in errors)
        assert any("tasks" in e for e in errors)

    def test_empty_tasks(self):
        errors = validate_cto_plan({"title": "X", "tasks": []})
        assert any("no tasks" in e for e in errors)

    def test_task_missing_fields(self):
        plan = {"title": "X", "tasks": [{"id": "t1"}]}
        errors = validate_cto_plan(plan)
        assert any("title" in e for e in errors)

    def test_valid_plan(self):
        plan = {
            "title": "My Project",
            "tasks": [
                {"id": "t1", "title": "Do thing", "description": "desc", "assigned_team": "backend_engineer"}
            ],
        }
        assert validate_cto_plan(plan) == []

    def test_unknown_dependency(self):
        plan = {
            "title": "X",
            "tasks": [
                {"id": "t1", "title": "A", "description": "d", "assigned_team": "be", "depends_on": ["t99"]}
            ],
        }
        errors = validate_cto_plan(plan)
        assert any("t99" in e for e in errors)


class TestValidateHRResponse:
    def test_no_members(self):
        resp = {"team": {"members": [], "lead_id": ""}, "persons": []}
        errors = validate_hr_response(resp, "test_team")
        assert any("no members" in e for e in errors)

    def test_lead_not_in_members(self):
        resp = {"team": {"members": ["a"], "lead_id": "b"}, "persons": [{"id": "a", "role": "dev", "identity": "x"}]}
        errors = validate_hr_response(resp, "t")
        assert any("not in members" in e for e in errors)

    def test_missing_person_definition(self):
        resp = {"team": {"members": ["a", "b"], "lead_id": "a"}, "persons": [{"id": "a", "role": "dev", "identity": "x"}]}
        errors = validate_hr_response(resp, "t")
        assert any("b" in e and "no corresponding" in e for e in errors)

    def test_valid(self):
        resp = {
            "team": {"members": ["a"], "lead_id": "a"},
            "persons": [{"id": "a", "role": "Lead", "identity": "I am lead"}],
        }
        assert validate_hr_response(resp, "t") == []
