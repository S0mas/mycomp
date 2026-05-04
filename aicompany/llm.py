import json
import re

import anthropic

from . import config

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        config.require_api_key()
        _client = anthropic.Anthropic()
    return _client


def _call(system: str, user: str, max_tokens: int) -> str:
    response = _get_client().messages.create(
        model=config.MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return response.content[0].text


def _extract_json_block(text: str) -> dict:
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


# ── CTO ────────────────────────────────────────────────────────────────────────

_CTO_SYSTEM = """\
You are the CTO of an AI-driven software company. Your job is to analyze a client's
requirements and produce a precise, structured project plan.

You have access to the company's current team registry (skills available). Reuse
existing team IDs wherever their skills match. Only list teams in `teams_required`
that are genuinely needed.

Output ONLY a JSON block (```json ... ```) with EXACTLY this schema — no prose before
or after:

```json
{
  "title": "Short project title (max 60 chars)",
  "tech_stack": ["technology1", "technology2"],
  "teams_required": ["team_id1", "team_id2"],
  "tasks": [
    {
      "id": "task_001",
      "title": "Task title",
      "description": "Detailed description of what needs to be done and expected output",
      "assigned_team": "team_id",
      "depends_on": [],
      "is_checkpoint": false
    }
  ]
}
```

Rules:
- team IDs must be snake_case (e.g., backend_engineer, devops_engineer)
- Reuse existing team IDs from the registry when their skills match the task
- Mark `is_checkpoint: true` for tasks involving: external services, deployment,
  payment/billing systems, security configuration, or any irreversible production action
- Task IDs must be sequential: task_001, task_002, ...
- `depends_on` lists task IDs that must complete before this task starts
- Keep tasks focused and achievable by one team in one session
- 4 to 10 tasks is typical; avoid over-splitting trivial work\
"""


def cto_analyze(requirements_text: str, company_state_yaml: str) -> dict:
    user = f"""\
## Client Requirements

{requirements_text}

## Current Company Registry (YAML)

```yaml
{company_state_yaml}
```
"""
    text = _call(_CTO_SYSTEM, user, config.MAX_TOKENS_CTO)
    return _extract_json_block(text)


# ── HR ─────────────────────────────────────────────────────────────────────────

_HR_SYSTEM = """\
You are the Head of HR at an AI-driven software company. Your job is to create a team
configuration for a new specialist agent.

Output ONLY a JSON block (```json ... ```) with EXACTLY this schema — no prose:

```json
{
  "id": "snake_case_team_id",
  "name": "Human Readable Team Name",
  "skills": ["skill1", "skill2", "skill3"],
  "system_prompt": "Full system prompt for this specialist AI agent",
  "tools": [],
  "context_notes": ""
}
```

The `system_prompt` field must:
- Define the specialist's role and core expertise clearly
- List preferred frameworks, tools, and languages
- Describe the expected output format (e.g., complete code files as Markdown)
- Be written in second person ("You are a senior X...")
- Be thorough — this is what the agent uses to do real work\
"""


def hr_create_team(skill_name: str, tech_context: str) -> dict:
    user = f"""\
Create a team configuration for a specialist in: **{skill_name}**

Technology context from the project: {tech_context}
"""
    text = _call(_HR_SYSTEM, user, config.MAX_TOKENS_HR)
    return _extract_json_block(text)


# ── Team Agent ─────────────────────────────────────────────────────────────────

def team_execute_task(team_system_prompt: str, task_title: str,
                      task_description: str, project_context: str) -> str:
    user = f"""\
## Your Task

**{task_title}**

{task_description}

## Project Context

{project_context}

---

Produce your complete output as Markdown. Be thorough and production-ready.
Include file paths, complete code, and brief explanations of key decisions.
"""
    return _call(team_system_prompt, user, config.MAX_TOKENS_TEAM)
