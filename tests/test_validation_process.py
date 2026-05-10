"""
Tests for aicompany/validation/ package.

What we verify:
  - ValidationPolicy: load, fallback default, caching, reload
  - ValidationResult: parse approved/rejected/dict-fix, unknown verdict → rejected, parse failure
  - ValidationProcess.run() loop: approved, retry with fix, exhausts attempts, stops on no fix
  - RequirementsValidation: team composition, lead rules, description, extract_fix
  - PlanValidation: team composition, lead rules, description, extract_fix, referential integrity

All LLM calls are mocked — no API key needed.
"""
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aicompany.config as config
from aicompany.validation.policy import ValidationPolicy
from aicompany.validation.result import ValidationResult
from aicompany.validation.process import ValidationProcess, ValidationError
from aicompany.validation.requirements_validation import RequirementsValidation
from aicompany.validation.plan_validation import PlanValidation, _check_requirement_refs
from aicompany.models import Person


# ── ValidationPolicy ───────────────────────────────────────────────────────────

class TestValidationPolicy:
    def test_loads_existing_file(self, tmp_path):
        p = tmp_path / "policy.md"
        p.write_text("# Policy\n- Rule A")
        policy = ValidationPolicy.from_path(p)
        assert "Rule A" in policy.load()

    def test_fallback_when_missing(self, tmp_path):
        policy = ValidationPolicy.from_path(tmp_path / "missing.md")
        text = policy.load()
        assert text == ValidationPolicy.DEFAULT_POLICY
        assert "best practices" in text

    def test_caches_after_first_load(self, tmp_path):
        p = tmp_path / "policy.md"
        p.write_text("original")
        policy = ValidationPolicy.from_path(p)
        policy.load()
        p.write_text("changed")
        assert policy.load() == "original"

    def test_reload_re_reads_disk(self, tmp_path):
        p = tmp_path / "policy.md"
        p.write_text("original")
        policy = ValidationPolicy.from_path(p)
        policy.load()
        p.write_text("changed")
        assert policy.reload() == "changed"


# ── ValidationResult ───────────────────────────────────────────────────────────

class TestValidationResult:
    def _json(self, **kw) -> str:
        data = {"verdict": "approved", "summary": "ok", "issues": [],
                "suggestions": [], "proposed_fix": None, **kw}
        return f"```json\n{json.dumps(data)}\n```"

    def test_parses_approved(self):
        result = ValidationResult.from_lead_output(self._json(verdict="approved"))
        assert result.approved
        assert not result.rejected
        assert result.proposed_fix is None

    def test_parses_rejected_with_string_fix(self):
        result = ValidationResult.from_lead_output(
            self._json(verdict="rejected", summary="too vague",
                       issues=["no actors"], proposed_fix="Better requirements text"))
        assert result.rejected
        assert result.proposed_fix == "Better requirements text"
        assert "no actors" in result.issues

    def test_parses_rejected_with_dict_fix(self):
        plan = {"title": "Fixed Plan", "tasks": []}
        result = ValidationResult.from_lead_output(
            self._json(verdict="rejected", proposed_fix=plan))
        assert result.rejected
        assert result.proposed_fix == plan

    def test_unknown_verdict_becomes_rejected(self):
        result = ValidationResult.from_lead_output(self._json(verdict="needs_work"))
        assert result.rejected

    def test_malformed_json_becomes_rejected(self):
        result = ValidationResult.from_lead_output("not json at all")
        assert result.rejected
        assert "parse" in result.summary.lower() or "failed" in result.summary.lower()
        assert result.parse_failed is True

    def test_valid_json_has_parse_failed_false(self):
        result = ValidationResult.from_lead_output(
            '```json\n{"verdict": "approved", "summary": "ok", "issues": [], "suggestions": [], "proposed_fix": null}\n```'
        )
        assert result.parse_failed is False

    def test_non_dict_json_becomes_rejected(self):
        result = ValidationResult.from_lead_output("```json\n[1, 2, 3]\n```")
        assert result.rejected


# ── ValidationProcess loop ─────────────────────────────────────────────────────

class _StubValidation(ValidationProcess):
    """Minimal concrete subclass for testing the loop mechanics."""
    _max_attempts = 3
    _lead = Person(id="stub_lead", name="Lead", role="lead",
                   identity="stub", knowledge=[], rules=[])
    _validators = [Person(id="stub_val", name="Val", role="reviewer",
                          identity="stub", knowledge=[], rules=[])]

    @property
    def policy(self):
        return ValidationPolicy.from_path(Path("/nonexistent"))

    def _build_task_description(self, artifact, attempt):
        return str(artifact)

    def _extract_fix(self, result, raw_output):
        fix = result.proposed_fix
        return fix if isinstance(fix, str) and fix.strip() else None


def _approved_json(fix=None):
    return f'```json\n{json.dumps({"verdict": "approved", "summary": "ok", "issues": [], "suggestions": [], "proposed_fix": fix})}\n```'

def _rejected_json(fix=None, summary="bad"):
    return f'```json\n{json.dumps({"verdict": "rejected", "summary": summary, "issues": [], "suggestions": [], "proposed_fix": fix})}\n```'


class TestValidationProcessLoop:
    _MOCK_SESSION = MagicMock()

    async def test_approved_on_first_attempt(self):
        with patch("aicompany.validation.process.run_pattern",
                   new=AsyncMock(return_value=_approved_json())), \
             patch("aicompany.validation.process.create_session",
                   return_value=self._MOCK_SESSION):
            artifact, result = await _StubValidation().run("original text")
        assert result.approved
        assert artifact == "original text"

    async def test_retries_with_proposed_fix(self):
        with patch("aicompany.validation.process.run_pattern",
                   new=AsyncMock(side_effect=[
                       _rejected_json(fix="fixed text"),
                       _approved_json(),
                   ])), \
             patch("aicompany.validation.process.create_session",
                   return_value=self._MOCK_SESSION):
            artifact, result = await _StubValidation().run("original text")
        assert result.approved
        assert artifact == "fixed text"

    async def test_raises_after_max_attempts(self):
        with patch("aicompany.validation.process.run_pattern",
                   new=AsyncMock(return_value=_rejected_json(fix="fix"))), \
             patch("aicompany.validation.process.create_session",
                   return_value=self._MOCK_SESSION):
            with pytest.raises(ValidationError) as exc_info:
                await _StubValidation().run("original")
        assert exc_info.value.last_result.rejected

    async def test_run_pattern_called_max_attempts_times(self):
        mock_pattern = AsyncMock(return_value=_rejected_json(fix="fix"))
        with patch("aicompany.validation.process.run_pattern", new=mock_pattern), \
             patch("aicompany.validation.process.create_session",
                   return_value=self._MOCK_SESSION):
            with pytest.raises(ValidationError):
                await _StubValidation().run("original")
        assert mock_pattern.call_count == 3

    async def test_stops_immediately_when_no_fix(self):
        mock_pattern = AsyncMock(return_value=_rejected_json(fix=None))
        with patch("aicompany.validation.process.run_pattern", new=mock_pattern), \
             patch("aicompany.validation.process.create_session",
                   return_value=self._MOCK_SESSION):
            with pytest.raises(ValidationError):
                await _StubValidation().run("original")
        assert mock_pattern.call_count == 1

    async def test_retries_on_parse_failure(self):
        mock_pattern = AsyncMock(side_effect=[
            "not valid json at all",
            _approved_json(),
        ])
        with patch("aicompany.validation.process.run_pattern", new=mock_pattern), \
             patch("aicompany.validation.process.create_session",
                   return_value=self._MOCK_SESSION):
            artifact, result = await _StubValidation().run("original")
        assert result.approved
        assert mock_pattern.call_count == 2

    async def test_parse_failure_exhausts_attempts(self):
        mock_pattern = AsyncMock(return_value="not valid json")
        with patch("aicompany.validation.process.run_pattern", new=mock_pattern), \
             patch("aicompany.validation.process.create_session",
                   return_value=self._MOCK_SESSION):
            with pytest.raises(ValidationError):
                await _StubValidation().run("original")
        assert mock_pattern.call_count == 3

    async def test_on_status_called(self):
        statuses = []
        with patch("aicompany.validation.process.run_pattern",
                   new=AsyncMock(return_value=_approved_json())), \
             patch("aicompany.validation.process.create_session",
                   return_value=self._MOCK_SESSION):
            await _StubValidation().run("x", on_status=statuses.append)
        assert len(statuses) > 0
        assert any("attempt" in s.lower() for s in statuses)


# ── RequirementsValidation ─────────────────────────────────────────────────────

class TestRequirementsValidation:
    def test_has_two_validators(self):
        assert len(RequirementsValidation._validators) == 2

    def test_lead_role_is_lead(self):
        assert RequirementsValidation._lead.role == "lead"

    def test_validators_are_reviewers(self):
        for v in RequirementsValidation._validators:
            assert v.role == "reviewer"

    def test_lead_has_json_output_rule(self):
        rules_text = " ".join(RequirementsValidation._lead.rules)
        assert "proposed_fix" in rules_text
        assert "json" in rules_text.lower()

    def test_build_description_includes_policy_and_artifact(self):
        config.REQUIREMENTS_POLICY_FILE.parent.mkdir(parents=True, exist_ok=True)
        config.REQUIREMENTS_POLICY_FILE.write_text("## Policy\n- Rule A", encoding="utf-8")
        val = RequirementsValidation()
        desc = val._build_task_description("User must log in.", 1)
        assert "Rule A" in desc
        assert "User must log in." in desc

    def test_build_description_shows_attempt_number_from_2(self):
        val = RequirementsValidation()
        desc = val._build_task_description("text", 2)
        assert "[Attempt 2]" in desc

    def test_build_description_no_prefix_on_attempt_1(self):
        val = RequirementsValidation()
        desc = val._build_task_description("text", 1)
        assert "[Attempt" not in desc

    def test_extract_fix_reads_proposal_file(self):
        proposal = config.BASE_DIR / "RequirementsProposal.md"
        proposal.write_text("Revised requirements here.\nMore text.", encoding="utf-8")
        val = RequirementsValidation()
        result = ValidationResult(verdict="rejected")
        assert val._extract_fix(result, "") == "Revised requirements here.\nMore text."

    def test_extract_fix_deletes_proposal_file_after_read(self):
        proposal = config.BASE_DIR / "RequirementsProposal.md"
        proposal.write_text("Some fix", encoding="utf-8")
        val = RequirementsValidation()
        val._extract_fix(ValidationResult(verdict="rejected"), "")
        assert not proposal.exists()

    def test_extract_fix_returns_none_when_no_file(self):
        val = RequirementsValidation()
        result = ValidationResult(verdict="rejected", proposed_fix=None)
        assert val._extract_fix(result, "") is None

    def test_extract_fix_returns_none_for_empty_file(self):
        proposal = config.BASE_DIR / "RequirementsProposal.md"
        proposal.write_text("   ", encoding="utf-8")
        val = RequirementsValidation()
        assert val._extract_fix(ValidationResult(verdict="rejected"), "") is None


# ── PlanValidation ─────────────────────────────────────────────────────────────

class TestPlanValidation:
    def test_has_three_validators(self):
        assert len(PlanValidation._validators) == 3

    def test_lead_role_is_lead(self):
        assert PlanValidation._lead.role == "lead"

    def test_validators_are_reviewers(self):
        for v in PlanValidation._validators:
            assert v.role == "reviewer"

    def test_lead_has_json_output_rule(self):
        rules_text = " ".join(PlanValidation._lead.rules)
        assert "proposed_fix" in rules_text
        assert "json" in rules_text.lower()

    def test_build_description_serialises_plan(self):
        val = PlanValidation()
        plan = {"title": "Test Plan", "tasks": [{"id": "t1"}]}
        desc = val._build_task_description(plan, 1)
        assert '"Test Plan"' in desc
        assert '"t1"' in desc

    def test_build_description_shows_attempt_from_2(self):
        val = PlanValidation()
        desc = val._build_task_description({}, 2)
        assert "[Attempt 2]" in desc

    def test_build_description_includes_structural_issues_when_refs_invalid(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config, "COMPANY_DIR", tmp_path)
        val = PlanValidation()
        plan = {
            "requirements": [{"id": "REQ-001", "title": "A", "sub_requirements": []}],
            "tasks": [{"id": "t1", "requirement_ids": ["REQ-GHOST"]}],
        }
        desc = val._build_task_description(plan, 1)
        assert "Structural Issues" in desc
        assert "REQ-GHOST" in desc
        assert "proposed_fix" in desc.lower() or "must be corrected" in desc

    def test_build_description_no_structural_section_when_refs_valid(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config, "COMPANY_DIR", tmp_path)
        val = PlanValidation()
        plan = {
            "requirements": [{"id": "REQ-001", "title": "A", "sub_requirements": []}],
            "tasks": [{"id": "t1", "requirement_ids": ["REQ-001"]}],
        }
        desc = val._build_task_description(plan, 1)
        assert "Structural Issues" not in desc

    def test_extract_fix_returns_dict(self):
        val = PlanValidation()
        plan = {"title": "Fixed", "tasks": []}
        result = ValidationResult(verdict="rejected", proposed_fix=plan)
        assert val._extract_fix(result, "") == plan

    def test_extract_fix_parses_json_string(self):
        val = PlanValidation()
        plan_str = '{"title": "Fixed", "tasks": []}'
        result = ValidationResult(verdict="rejected", proposed_fix=plan_str)
        extracted = val._extract_fix(result, "")
        assert extracted == {"title": "Fixed", "tasks": []}

    def test_extract_fix_returns_none_for_plain_text(self):
        val = PlanValidation()
        result = ValidationResult(verdict="rejected", proposed_fix="just text")
        assert val._extract_fix(result, "") is None

    def test_extract_fix_returns_none_for_empty_dict(self):
        val = PlanValidation()
        result = ValidationResult(verdict="rejected", proposed_fix={})
        assert val._extract_fix(result, "") is None

    def test_extract_fix_returns_none_for_none(self):
        val = PlanValidation()
        result = ValidationResult(verdict="rejected", proposed_fix=None)
        assert val._extract_fix(result, "") is None

    def test_extract_fix_returns_none_when_fix_has_invalid_refs(self):
        val = PlanValidation()
        fix = {
            "requirements": [{"id": "REQ-001", "title": "Auth", "sub_requirements": []}],
            "tasks": [{"id": "t1", "requirement_ids": ["REQ-999"]}],
        }
        result = ValidationResult(verdict="rejected", proposed_fix=fix)
        assert val._extract_fix(result, "") is None

    def test_extract_fix_accepts_fix_with_valid_refs(self):
        val = PlanValidation()
        fix = {
            "requirements": [{"id": "REQ-001", "title": "Auth", "sub_requirements": []}],
            "tasks": [{"id": "t1", "requirement_ids": ["REQ-001"]}],
        }
        result = ValidationResult(verdict="rejected", proposed_fix=fix)
        assert val._extract_fix(result, "") == fix


# ── _check_requirement_refs ────────────────────────────────────────────────────


class TestCheckRequirementRefs:
    def _plan(self, req_ids, task_req_ids):
        reqs = [{"id": rid, "title": rid, "sub_requirements": []} for rid in req_ids]
        tasks = [{"id": "t1", "requirement_ids": task_req_ids}]
        return {"requirements": reqs, "tasks": tasks}

    def test_passes_when_all_refs_valid(self):
        _check_requirement_refs(self._plan(["REQ-001", "REQ-002"], ["REQ-001"]))

    def test_passes_when_no_requirement_ids_on_task(self):
        plan = {"requirements": [], "tasks": [{"id": "t1", "requirement_ids": []}]}
        _check_requirement_refs(plan)

    def test_passes_with_sub_requirement_refs(self):
        plan = {
            "requirements": [{
                "id": "REQ-001", "title": "Auth",
                "sub_requirements": [{"id": "REQ-001-A", "title": "Login"}],
            }],
            "tasks": [{"id": "t1", "requirement_ids": ["REQ-001-A"]}],
        }
        _check_requirement_refs(plan)

    def test_raises_for_unknown_id(self):
        with pytest.raises(ValueError, match="REQ-999"):
            _check_requirement_refs(self._plan(["REQ-001"], ["REQ-999"]))

    def test_raises_lists_all_bad_ids(self):
        plan = {
            "requirements": [{"id": "REQ-001", "title": "A", "sub_requirements": []}],
            "tasks": [{"id": "t1", "requirement_ids": ["REQ-999", "REQ-888"]}],
        }
        with pytest.raises(ValueError) as exc_info:
            _check_requirement_refs(plan)
        msg = str(exc_info.value)
        assert "REQ-999" in msg
        assert "REQ-888" in msg

    def test_raises_lists_all_bad_tasks(self):
        plan = {
            "requirements": [{"id": "REQ-001", "title": "A", "sub_requirements": []}],
            "tasks": [
                {"id": "t1", "requirement_ids": ["REQ-BAD"]},
                {"id": "t2", "requirement_ids": ["REQ-BAD2"]},
            ],
        }
        with pytest.raises(ValueError) as exc_info:
            _check_requirement_refs(plan)
        msg = str(exc_info.value)
        assert "t1" in msg
        assert "t2" in msg

    def test_passes_with_empty_plan(self):
        _check_requirement_refs({})

    def test_passes_with_no_tasks_key(self):
        _check_requirement_refs({"requirements": [{"id": "REQ-001", "title": "A", "sub_requirements": []}]})


# ── PlanValidation.run() referential integrity ─────────────────────────────────


class TestPlanValidationRequirementRefs:
    """Invalid refs surface as AI feedback; approved plans with broken refs are hard-rejected."""

    _approved = '```json\n{"verdict": "approved", "summary": "ok", "issues": [], "suggestions": [], "proposed_fix": null}\n```'

    async def test_ai_runs_even_when_refs_invalid(self, monkeypatch, tmp_path):
        """AI panel should run so it can produce a fix; invalid refs appear in description."""
        bad_plan = {
            "requirements": [{"id": "REQ-001", "title": "A", "sub_requirements": []}],
            "tasks": [{"id": "t1", "requirement_ids": ["REQ-GHOST"]}],
        }
        fixed_plan = {
            "requirements": [{"id": "REQ-001", "title": "A", "sub_requirements": []}],
            "tasks": [{"id": "t1", "requirement_ids": ["REQ-001"]}],
        }
        reject_output = (
            '```json\n{"verdict": "rejected", "summary": "bad ref", "issues": ["REQ-GHOST unknown"], '
            '"suggestions": [], "proposed_fix": '
            + json.dumps(fixed_plan)
            + '}\n```'
        )
        approve_output = self._approved
        responses = iter([reject_output, approve_output])

        async def fake_run_pattern(*args, **kwargs):
            return next(responses)

        monkeypatch.setattr("aicompany.validation.process.run_pattern", fake_run_pattern)
        monkeypatch.setattr(config, "COMPANY_DIR", tmp_path)
        result_plan, _ = await PlanValidation().run(bad_plan)
        assert result_plan == fixed_plan

    async def test_run_raises_if_ai_approves_plan_with_invalid_refs(self, monkeypatch, tmp_path):
        """If AI incorrectly approves a plan that still has invalid refs, run() hard-fails."""
        bad_plan = {
            "requirements": [{"id": "REQ-001", "title": "A", "sub_requirements": []}],
            "tasks": [{"id": "t1", "requirement_ids": ["REQ-GHOST"]}],
        }
        monkeypatch.setattr(
            "aicompany.validation.process.run_pattern",
            AsyncMock(return_value=self._approved),
        )
        monkeypatch.setattr(config, "COMPANY_DIR", tmp_path)
        with pytest.raises(ValueError, match="REQ-GHOST"):
            await PlanValidation().run(bad_plan)

    async def test_run_succeeds_with_valid_refs(self, monkeypatch, tmp_path):
        good_plan = {
            "requirements": [{"id": "REQ-001", "title": "A", "sub_requirements": []}],
            "tasks": [{"id": "t1", "requirement_ids": ["REQ-001"]}],
        }
        monkeypatch.setattr(
            "aicompany.validation.process.run_pattern",
            AsyncMock(return_value=self._approved),
        )
        monkeypatch.setattr(config, "COMPANY_DIR", tmp_path)
        result_plan, _ = await PlanValidation().run(good_plan)
        assert result_plan == good_plan
