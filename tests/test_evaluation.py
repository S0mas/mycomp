"""
Tests for aicompany/evaluation.py

What we verify:
  - extract_json_block parses ```json blocks and bare JSON
  - load_policy returns policy text when file exists, fallback when not
  - evaluate_requirements returns a RequirementsEvaluation with correct verdict
  - evaluate_sub_requirements returns one result per sub-requirement
  - evaluate_sub_requirements handles empty input without LLM call

All LLM calls are mocked — no API key needed.
"""
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import aicompany.config as config
from aicompany.evaluation import (
    extract_json_block,
    load_policy,
    evaluate_requirements,
    evaluate_sub_requirements,
    SubRequirementEvaluation,
)
from aicompany.models import RequirementsEvaluation, SubRequirement


# ── extract_json_block ─────────────────────────────────────────────────────────

class TestExtractJsonBlock:
    def test_parses_json_fenced_block(self):
        text = '```json\n{"key": "value"}\n```'
        result = extract_json_block(text)
        assert result == {"key": "value"}

    def test_parses_generic_fenced_block(self):
        text = '```\n{"key": 42}\n```'
        result = extract_json_block(text)
        assert result == {"key": 42}

    def test_parses_bare_json(self):
        result = extract_json_block('{"a": true}')
        assert result == {"a": True}

    def test_parses_json_list(self):
        text = '```json\n[{"id": "x"}]\n```'
        result = extract_json_block(text)
        assert result == [{"id": "x"}]

    def test_raises_on_invalid_json(self):
        with pytest.raises(Exception):
            extract_json_block("not json at all")


# ── load_policy ────────────────────────────────────────────────────────────────

class TestLoadPolicy:
    def test_returns_policy_when_file_exists(self):
        policy_text = "# Policy\nMust have acceptance criteria."
        config.REQUIREMENTS_POLICY_FILE.parent.mkdir(parents=True, exist_ok=True)
        config.REQUIREMENTS_POLICY_FILE.write_text(policy_text, encoding="utf-8")
        result = load_policy()
        assert "acceptance criteria" in result

    def test_returns_fallback_when_file_missing(self):
        if config.REQUIREMENTS_POLICY_FILE.exists():
            config.REQUIREMENTS_POLICY_FILE.unlink()
        result = load_policy()
        assert "No requirements policy" in result or len(result) > 0


# ── evaluate_requirements ──────────────────────────────────────────────────────

class TestEvaluateRequirements:
    _GOOD_EVAL = json.dumps({
        "clarity": 5,
        "completeness": 4,
        "feasibility": 4,
        "violations": [],
        "risks": [],
        "suggestions": [],
        "summary": "Well-written requirements.",
        "verdict": "proceed",
    })

    _REJECT_EVAL = json.dumps({
        "clarity": 1,
        "completeness": 2,
        "feasibility": 3,
        "violations": ["Missing acceptance criteria"],
        "risks": ["Unclear scope"],
        "suggestions": ["Add testable criteria"],
        "summary": "Rejected — too vague.",
        "verdict": "reject",
    })

    @pytest.mark.asyncio
    async def test_returns_requirements_evaluation(self):
        with patch("aicompany.evaluation._query",
                   new=AsyncMock(return_value=f"```json\n{self._GOOD_EVAL}\n```")):
            result = await evaluate_requirements("# Build a user auth system")
        assert isinstance(result, RequirementsEvaluation)
        assert result.verdict == "proceed"
        assert result.clarity == 5

    @pytest.mark.asyncio
    async def test_returns_reject_verdict(self):
        with patch("aicompany.evaluation._query",
                   new=AsyncMock(return_value=f"```json\n{self._REJECT_EVAL}\n```")):
            result = await evaluate_requirements("# vague requirement")
        assert result.verdict == "reject"
        assert len(result.violations) == 1

    @pytest.mark.asyncio
    async def test_calls_query_once(self):
        mock_query = AsyncMock(return_value=f"```json\n{self._GOOD_EVAL}\n```")
        with patch("aicompany.evaluation._query", new=mock_query):
            await evaluate_requirements("some requirements text")
        mock_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_policy_is_included_in_system_prompt(self):
        config.REQUIREMENTS_POLICY_FILE.parent.mkdir(parents=True, exist_ok=True)
        config.REQUIREMENTS_POLICY_FILE.write_text("# Custom Policy\nRule: no vague scope.", encoding="utf-8")

        captured = {}

        async def _capture(system, prompt):
            captured["system"] = system
            return f"```json\n{self._GOOD_EVAL}\n```"

        with patch("aicompany.evaluation._query", new=_capture):
            await evaluate_requirements("requirements")
        assert "Custom Policy" in captured["system"]


# ── evaluate_sub_requirements ──────────────────────────────────────────────────

class TestEvaluateSubRequirements:
    _BATCH_EVAL = json.dumps([
        {"id": "REQ-0001-001", "verdict": "proceed", "issues": [], "suggestions": []},
        {"id": "REQ-0001-002", "verdict": "needs_work", "issues": ["Missing error path"],
         "suggestions": ["Add failure acceptance criterion"]},
    ])

    def _make_sub(self, sid, title="A sub-req"):
        return SubRequirement(
            id=sid, parent_id="REQ-0001", title=title,
            description="Do something specific.", acceptance_criteria=["Given X, when Y, then Z"],
        )

    @pytest.mark.asyncio
    async def test_returns_empty_for_empty_input(self):
        mock_query = AsyncMock()
        with patch("aicompany.evaluation._query", new=mock_query):
            result = await evaluate_sub_requirements([])
        assert result == []
        mock_query.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_one_result_per_sub_req(self):
        subs = [self._make_sub("REQ-0001-001"), self._make_sub("REQ-0001-002")]
        with patch("aicompany.evaluation._query",
                   new=AsyncMock(return_value=f"```json\n{self._BATCH_EVAL}\n```")):
            results = await evaluate_sub_requirements(subs)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_parses_verdict_and_issues(self):
        subs = [self._make_sub("REQ-0001-001"), self._make_sub("REQ-0001-002")]
        with patch("aicompany.evaluation._query",
                   new=AsyncMock(return_value=f"```json\n{self._BATCH_EVAL}\n```")):
            results = await evaluate_sub_requirements(subs)

        proceed = next(r for r in results if r.id == "REQ-0001-001")
        needs_work = next(r for r in results if r.id == "REQ-0001-002")
        assert proceed.passed
        assert not proceed.failed
        assert needs_work.verdict == "needs_work"
        assert "Missing error path" in needs_work.issues

    @pytest.mark.asyncio
    async def test_handles_single_dict_response(self):
        single = json.dumps(
            {"id": "REQ-0001-001", "verdict": "proceed", "issues": [], "suggestions": []}
        )
        with patch("aicompany.evaluation._query",
                   new=AsyncMock(return_value=f"```json\n{single}\n```")):
            results = await evaluate_sub_requirements([self._make_sub("REQ-0001-001")])
        assert len(results) == 1
        assert results[0].verdict == "proceed"
