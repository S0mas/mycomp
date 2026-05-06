import json
import re
import time
from pathlib import Path

import httpx

from . import config
from .llm_backend import LLMBackend, create_backend

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    """Load a system prompt template from the prompts/ directory."""
    return (_PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8").strip()


def _get_backend() -> LLMBackend:
    """Create a fresh backend instance. No global state."""
    from . import backends  # noqa: F401 — trigger auto-registration
    return create_backend(config.LLM_BACKEND)


def _call(system: str, user: str, max_tokens: int, backend: LLMBackend | None = None) -> str:
    b = backend or _get_backend()
    for attempt in range(config.LLM_RETRY_ATTEMPTS):
        try:
            return b.call(system, user, max_tokens, config.MODEL)
        except Exception as exc:
            if attempt == config.LLM_RETRY_ATTEMPTS - 1:
                raise
            if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
                raise
            time.sleep(config.LLM_RETRY_BACKOFF_BASE ** attempt)


def extract_json_block(text: str) -> dict:
    # Try ```json ... ``` fence first
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    # Fallback: any ``` ... ``` block
    match = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    # Last resort: parse whole text
    return json.loads(text)


# ── Requirements evaluation ───────────────────────────────────────────────────

def evaluate_requirements(requirements_text: str, company_state_yaml: str) -> dict:
    """Evaluate requirements before CTO planning. Returns evaluation dict."""
    user = f"""\
## Client Requirements to Evaluate

{requirements_text}

## Current Company Capabilities (YAML)

```yaml
{company_state_yaml}
```

Evaluate these requirements. Be honest and constructive.
"""
    text = _call(_load_prompt("eval_system"), user, config.MAX_TOKENS_EVAL)
    return extract_json_block(text)


# ── Autofix ────────────────────────────────────────────────────────────────────


def autofix_requirements(
    requirements_text: str,
    evaluation_dict: dict,
) -> str:
    """Rewrite requirements to fix evaluation issues. Returns improved Markdown text."""
    user = f"""\
## Original Requirements

{requirements_text}

## Evaluation Results

- Clarity: {evaluation_dict.get('clarity', '?')}/5
- Completeness: {evaluation_dict.get('completeness', '?')}/5
- Feasibility: {evaluation_dict.get('feasibility', '?')}/5
- Risks: {', '.join(evaluation_dict.get('risks', []))}
- Suggestions: {', '.join(evaluation_dict.get('suggestions', []))}
- Summary: {evaluation_dict.get('summary', '')}

Rewrite the requirements to address all issues. Mark any assumptions with [ASSUMED].
"""
    return _call(_load_prompt("autofix_system"), user, config.MAX_TOKENS_AUTOFIX)


# ── HR ─────────────────────────────────────────────────────────────────────────


def hr_create_team(skill_name: str, tech_context: str) -> dict:
    """Returns dict with keys 'team' and 'persons'."""
    user = f"""\
Create a team for a project requiring: **{skill_name}**

Technology context: {tech_context}
"""
    text = _call(_load_prompt("hr_system"), user, config.MAX_TOKENS_HR)
    return extract_json_block(text)
