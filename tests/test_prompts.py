"""Tests for prompt template loading in aicompany/llm.py"""
from pathlib import Path

from aicompany.llm import _load_prompt


_PROMPTS_DIR = Path(__file__).parent.parent / "aicompany" / "prompts"


class TestPromptTemplates:
    def test_all_prompt_files_exist(self):
        for name in ("cto_system", "eval_system", "autofix_system", "hr_system"):
            path = _PROMPTS_DIR / f"{name}.txt"
            assert path.exists(), f"Missing prompt template: {path}"

    def test_load_prompt_returns_non_empty(self):
        for name in ("cto_system", "eval_system", "autofix_system", "hr_system"):
            text = _load_prompt(name)
            assert len(text) > 100, f"Prompt {name} seems too short"

    def test_cto_prompt_contains_json_schema(self):
        text = _load_prompt("cto_system")
        assert "title" in text
        assert "tasks" in text
        assert "assigned_team" in text

    def test_eval_prompt_contains_dimensions(self):
        text = _load_prompt("eval_system")
        assert "clarity" in text
        assert "completeness" in text
        assert "feasibility" in text

    def test_hr_prompt_contains_person_schema(self):
        text = _load_prompt("hr_system")
        assert "identity" in text
        assert "skills" in text
        assert "knowledge" in text
