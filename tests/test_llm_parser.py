"""
Tests for the JSON extraction logic in aicompany/llm.py

What we verify:
  - _extract_json_block handles ```json fences correctly
  - Falls back to bare ``` fences
  - Falls back to raw JSON (no fence)
  - Raises json.JSONDecodeError on invalid JSON
  - Works with real CTO-shaped and HR-shaped payloads

We import _extract_json_block directly — it's a private helper but is the
most failure-prone part of the LLM pipeline (malformed model output breaks
the whole flow), so it deserves its own tests.
"""
import json
import pytest

from aicompany.llm import _extract_json_block


VALID_PLAN = {
    "title": "Test API",
    "tech_stack": ["python", "fastapi"],
    "teams_required": ["backend_engineer"],
    "tasks": [
        {
            "id": "task_001",
            "title": "Design schema",
            "description": "Create DB tables",
            "assigned_team": "backend_engineer",
            "depends_on": [],
            "is_checkpoint": False,
        }
    ],
}

VALID_TEAM = {
    "id": "devops_engineer",
    "name": "DevOps Engineer",
    "skills": ["docker", "kubernetes"],
    "identity": "You are a senior DevOps engineer.",
    "knowledge": [],
    "rules": ["Write infrastructure as code"],
}


class TestExtractJsonBlock:
    def test_json_fence(self):
        text = f"Here is the plan:\n```json\n{json.dumps(VALID_PLAN)}\n```"
        result = _extract_json_block(text)
        assert result["title"] == "Test API"
        assert len(result["tasks"]) == 1

    def test_bare_fence_fallback(self):
        text = f"```\n{json.dumps(VALID_TEAM)}\n```"
        result = _extract_json_block(text)
        assert result["id"] == "devops_engineer"

    def test_raw_json_fallback(self):
        result = _extract_json_block(json.dumps(VALID_PLAN))
        assert result["title"] == "Test API"

    def test_json_fence_with_surrounding_prose(self):
        text = (
            "I've analysed the requirements. Here is my structured plan:\n\n"
            f"```json\n{json.dumps(VALID_PLAN, indent=2)}\n```\n\n"
            "Let me know if you want changes."
        )
        result = _extract_json_block(text)
        assert result["tech_stack"] == ["python", "fastapi"]

    def test_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _extract_json_block("```json\n{ not valid json }\n```")

    def test_nested_structure_preserved(self):
        result = _extract_json_block(f"```json\n{json.dumps(VALID_PLAN)}\n```")
        task = result["tasks"][0]
        assert task["depends_on"] == []
        assert task["is_checkpoint"] is False

    def test_pretty_printed_json(self):
        pretty = json.dumps(VALID_PLAN, indent=2)
        result = _extract_json_block(f"```json\n{pretty}\n```")
        assert result["title"] == "Test API"

    def test_unicode_content(self):
        payload = {"title": "Héllo Wörld", "tech_stack": ["python"]}
        result = _extract_json_block(f"```json\n{json.dumps(payload)}\n```")
        assert result["title"] == "Héllo Wörld"
