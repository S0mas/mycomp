"""
Requirements evaluation against the company policy.

Uses claude-code-sdk query() — one-shot calls, no persistent process needed.
The policy is loaded from company/requirements_policy.md (seeded on init, editable).

Two entry points:
  evaluate_requirements(text)         — full requirements document
  evaluate_sub_requirements(subs)     — batch of CTO-generated sub-requirements
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from . import config
from .models import RequirementsEvaluation, SubRequirement

if TYPE_CHECKING:
    pass


# ── JSON utility (shared with planning.py) ────────────────────────────────────

def extract_json_block(text: str) -> dict | list:
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    match = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    return json.loads(text)


# ── Policy loading ────────────────────────────────────────────────────────────

def load_policy() -> str:
    path = config.REQUIREMENTS_POLICY_FILE
    if not path.exists():
        return "(No requirements policy on file. Evaluate against general software engineering best practices.)"
    return path.read_text(encoding="utf-8").strip()


# ── System prompts ────────────────────────────────────────────────────────────

_EVAL_SYSTEM = """\
You are a requirements evaluator. Assess requirements against the company policy below.

**Company Requirements Policy:**
{policy}

---

Return ONLY a ```json block — no prose before or after:

```json
{{
  "clarity": <1-5>,
  "completeness": <1-5>,
  "feasibility": <1-5>,
  "violations": ["exact policy clause violated, if any"],
  "risks": ["identified risks that could affect delivery"],
  "suggestions": ["concrete, actionable improvements"],
  "summary": "one sentence overall assessment",
  "verdict": "proceed|needs_work|reject"
}}
```

Scoring guide:
  5 — Excellent, no issues
  4 — Good, minor gaps only
  3 — Adequate, needs improvement before implementation
  2 — Poor, significant issues that will cause problems
  1 — Unacceptable, fundamental problems

verdict rules:
  proceed     — all scores >= 3 and no policy violations
  needs_work  — any score == 3 or minor violations (can proceed with caution)
  reject      — any score < 3 or automatic rejection trigger violated
"""

_SUB_REQ_SYSTEM = """\
You are a requirements evaluator. Assess the given sub-requirements against the company policy below.

**Company Requirements Policy:**
{policy}

---

Evaluate each sub-requirement listed and return ONLY a ```json block — no prose:

```json
[
  {{
    "id": "REQ-XXXX-NNN",
    "verdict": "proceed|needs_work|reject",
    "issues": ["specific issue with this sub-requirement"],
    "suggestions": ["concrete improvement"]
  }}
]
```

Use the same verdict rules: reject if acceptance criteria are missing or trivial,
needs_work if weak but fixable, proceed if policy-compliant.
"""


# ── SDK query helper ──────────────────────────────────────────────────────────

async def _query(system: str, prompt: str) -> str:
    from claude_code_sdk import query, ClaudeCodeOptions, AssistantMessage, TextBlock

    text = ""
    async for msg in query(
        prompt=prompt,
        options=ClaudeCodeOptions(
            system_prompt=system,
            permission_mode="bypassPermissions",
            max_turns=1,
        ),
    ):
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock) and block.text:
                    text += block.text
    return text


# ── Sub-requirement result ────────────────────────────────────────────────────

@dataclass
class SubRequirementEvaluation:
    id: str
    verdict: str  # proceed | needs_work | reject
    issues: list = field(default_factory=list)
    suggestions: list = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.verdict == "proceed"

    @property
    def failed(self) -> bool:
        return self.verdict == "reject"


# ── Public API ────────────────────────────────────────────────────────────────

async def evaluate_requirements(text: str) -> RequirementsEvaluation:
    """Evaluate a full requirements document against the company policy."""
    policy = load_policy()
    system = _EVAL_SYSTEM.format(policy=policy)
    response = await _query(system, f"Evaluate these requirements:\n\n{text}")
    data = extract_json_block(response)
    return RequirementsEvaluation.from_dict(data)


async def evaluate_sub_requirements(
    sub_reqs: list[SubRequirement],
) -> list[SubRequirementEvaluation]:
    """Evaluate a batch of sub-requirements. Returns one result per sub-requirement."""
    if not sub_reqs:
        return []

    policy = load_policy()
    system = _SUB_REQ_SYSTEM.format(policy=policy)

    lines: list[str] = []
    for sub in sub_reqs:
        lines.append(f"**{sub.id} — {sub.title}**")
        lines.append(f"Description: {sub.description}")
        if sub.acceptance_criteria:
            lines.append("Acceptance criteria:")
            for ac in sub.acceptance_criteria:
                lines.append(f"  - {ac}")
        lines.append("")

    response = await _query(system, "\n".join(lines))
    data = extract_json_block(response)

    if not isinstance(data, list):
        data = [data]

    return [
        SubRequirementEvaluation(
            id=item.get("id", "?"),
            verdict=item.get("verdict", "proceed"),
            issues=item.get("issues", []),
            suggestions=item.get("suggestions", []),
        )
        for item in data
    ]
