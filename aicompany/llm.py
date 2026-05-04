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
- team IDs must be snake_case (e.g., backend_team, frontend_team)
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


# ── Requirements evaluation ───────────────────────────────────────────────────

_EVAL_SYSTEM = """\
You are a senior Business Analyst at an AI-driven software company. Your job is to
evaluate client requirements documents BEFORE they go to the CTO for planning.

Score each dimension from 1 (very poor) to 5 (excellent):
- **clarity**: Are the requirements clear and unambiguous? Can an engineer read them and know exactly what to build?
- **completeness**: Do they cover scope, constraints, acceptance criteria, edge cases? Or are major pieces missing?
- **feasibility**: Given that an AI team of coders and reviewers will implement this, is the scope realistic for a single project?

Identify specific **risks** — things that could cause the project to fail, stall, or deliver the wrong thing.

Provide actionable **suggestions** — specific improvements the client could make to the requirements.

Set **verdict** to:
- "proceed" — requirements are good enough to plan (scores mostly 3+, no critical risks)
- "needs_work" — requirements have gaps that should be fixed first (any score below 3, or critical risks)
- "reject" — requirements are fundamentally unsuitable (incoherent, empty, or not a software project)

Output ONLY a JSON block (```json ... ```) with EXACTLY this schema — no prose:

```json
{
  "clarity": 4,
  "completeness": 3,
  "feasibility": 5,
  "risks": [
    "No authentication requirements specified — security gap",
    "Database choice not mentioned — may cause rework"
  ],
  "suggestions": [
    "Add acceptance criteria for each feature",
    "Specify target deployment environment"
  ],
  "summary": "One paragraph overall assessment of the requirements.",
  "verdict": "proceed"
}
```\
"""


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
    text = _call(_EVAL_SYSTEM, user, config.MAX_TOKENS_EVAL)
    return _extract_json_block(text)


# ── HR ─────────────────────────────────────────────────────────────────────────

_HR_SYSTEM = """\
You are the Head of HR at an AI-driven software company. A "team" is a group of
specialist AI agents (persons) who collaborate on tasks. Each person has a specific
role: lead, coder, reviewer, architect, or specialist.

Each person has structured context instead of a monolithic system prompt:
- `identity`: a short, stable description ("You are a senior X...")
- `skills`: list of skill IDs they reference from the shared skill registry
- `knowledge`: person-specific things they know (learned over time)
- `rules`: behavioural rules — how they work and communicate

When asked to create a team for a skill, design 2-4 persons that together cover the
work. One person must have role "lead" — they coordinate the others.
Also define any new skills that the team needs (if they don't already exist).

Output ONLY a JSON block (```json ... ```) with EXACTLY this schema — no prose:

```json
{
  "team": {
    "id": "snake_case_team_id",
    "name": "Human Readable Team Name",
    "skills": ["skill_id_1", "skill_id_2"],
    "members": ["person_id_1", "person_id_2"],
    "lead_id": "person_id_1"
  },
  "persons": [
    {
      "id": "person_id_1",
      "name": "Full Name / Title",
      "role": "lead",
      "identity": "You are a ... Your job is to ...",
      "skills": ["skill_id_1", "skill_id_2"],
      "knowledge": ["Person-specific knowledge item"],
      "rules": ["How this person works and communicates"],
      "tools": []
    }
  ],
  "skills": [
    {
      "id": "skill_id_1",
      "name": "Human Readable Skill Name",
      "category": "language|framework|tool|practice",
      "knowledge": [
        "Technical fact that anyone with this skill should know",
        "Another piece of knowledge"
      ]
    }
  ]
}
```

Rules for person context:
- `identity` must define the person's role in second person ("You are a senior X...")
- `skills` must reference skill IDs defined in the `skills` array or existing in the registry
- `knowledge` contains person-specific experience — NOT duplicated from skills
- `rules` define output format, communication style, and behavioural constraints
- Be thorough — this drives real work\
"""


def hr_create_team(skill_name: str, tech_context: str) -> dict:
    """Returns dict with keys 'team' and 'persons'."""
    user = f"""\
Create a team for a project requiring: **{skill_name}**

Technology context: {tech_context}
"""
    text = _call(_HR_SYSTEM, user, config.MAX_TOKENS_HR)
    return _extract_json_block(text)


# ── Multi-person team execution ────────────────────────────────────────────────

def team_brief(lead_system_prompt: str, task_title: str, task_description: str,
               project_context: str, team_members: list) -> str:
    """Lead produces a work brief assigning sub-tasks to each team member."""
    member_list = "\n".join(
        f"- {m['name']} (role: {m['role']}, id: {m['id']})" for m in team_members
    )
    user = f"""\
## Task to plan

**{task_title}**

{task_description}

## Project Context

{project_context}

## Your team members

{member_list}

---

As team lead, produce a brief that:
1. Summarises the overall approach
2. Assigns a specific sub-task to each team member by their name
3. Specifies what each member should produce

Format as Markdown. Be concise and directive.
"""
    return _call(lead_system_prompt, user, config.MAX_TOKENS_HR)


def person_execute(person_system_prompt: str, person_name: str, brief: str,
                   task_title: str) -> str:
    """A team member executes their assigned sub-task from the brief."""
    user = f"""\
## Team Brief for: {task_title}

{brief}

---

You are **{person_name}**. Execute your assigned sub-task from the brief above.
Produce complete, production-ready output as Markdown with fenced code blocks.
"""
    return _call(person_system_prompt, user, config.MAX_TOKENS_TEAM)


def team_synthesize(lead_system_prompt: str, task_title: str,
                    contributions: list) -> str:
    """Lead synthesizes all member contributions into the final task output."""
    contrib_text = "\n\n---\n\n".join(
        f"### Contribution from {c['name']}\n\n{c['output']}" for c in contributions
    )
    user = f"""\
## Task: {task_title}

Your team has completed their individual contributions. Synthesize them into a
single, coherent, production-ready output.

## Team Contributions

{contrib_text}

---

Produce the final unified output as Markdown. Resolve any conflicts, remove
duplication, and ensure consistency. This is the deliverable.
"""
    return _call(lead_system_prompt, user, config.MAX_TOKENS_TEAM)
