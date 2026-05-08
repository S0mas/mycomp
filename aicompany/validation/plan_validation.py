from __future__ import annotations

import json
from typing import Any

from .. import config
from ..models import Person
from .policy import ValidationPolicy
from .process import ValidationProcess
from .result import ValidationResult

_JSON_RULES = [
    "Output ONLY a ```json block — no prose before or after.",
    'The JSON must have exactly these keys: "verdict" ("approved" or "rejected"), '
    '"summary" (one sentence), "issues" (list of strings), '
    '"suggestions" (list of strings), '
    '"proposed_fix" (the FULL revised plan as a JSON object if rejecting, null if approving).',
    "Set verdict=approved only when the plan is traceable, feasible, and structurally complete.",
    "When rejecting, proposed_fix must be the complete revised plan dict — not a diff.",
]


class PlanValidation(ValidationProcess):
    """Validates a CTO plan dict against plan_policy.md.

    Team: architecture reviewer + requirements tracer + feasibility reviewer.
    Lead synthesises their feedback into a structured verdict with optional fix.
    """

    _max_attempts = 3

    _lead = Person(
        id="plan_val_lead",
        name="Plan Validation Lead",
        role="lead",
        identity=(
            "You are a senior architect leading a plan validation panel. "
            "You synthesise your team's multi-perspective assessment and produce a "
            "structured verdict on whether the CTO's plan is sound and traceable."
        ),
        knowledge=["software architecture", "project planning", "requirements traceability"],
        rules=_JSON_RULES,
    )

    _validators = [
        Person(
            id="plan_val_arch",
            name="Architecture Reviewer",
            role="reviewer",
            identity=(
                "You are an architecture reviewer who evaluates plans for task "
                "decomposition quality, dependency correctness, and tech stack coherence."
            ),
            knowledge=["system design", "dependency graphs", "tech stack selection"],
            rules=["Focus on task structure, dependency validity, and tech coherence."],
        ),
        Person(
            id="plan_val_tracer",
            name="Requirements Tracer",
            role="reviewer",
            identity=(
                "You are a requirements traceability specialist. Check that every "
                "requirement_id in the requirements list is covered by at least one task, "
                "and that no task references an undefined requirement ID."
            ),
            knowledge=["requirements traceability", "coverage analysis"],
            rules=["Focus exclusively on requirement-to-task traceability."],
        ),
        Person(
            id="plan_val_feasibility",
            name="Feasibility Reviewer",
            role="reviewer",
            identity=(
                "You are a delivery feasibility specialist who evaluates whether the "
                "plan's scope, team assignments, and timeline are realistic."
            ),
            knowledge=["project management", "capacity planning", "risk assessment"],
            rules=["Focus on realistic scope and delivery feasibility."],
        ),
    ]

    @property
    def policy(self) -> ValidationPolicy:
        return ValidationPolicy.from_path(config.COMPANY_DIR / "plan_policy.md")

    def _build_task_description(self, artifact: dict, attempt: int) -> str:
        policy_text = self.policy.load()
        plan_json = json.dumps(artifact, indent=2)
        prefix = f"[Attempt {attempt}] " if attempt > 1 else ""
        return (
            f"{prefix}Validate the following CTO plan against the plan policy.\n\n"
            f"## Plan Policy\n\n{policy_text}\n\n"
            f"## Plan Under Review\n\n```json\n{plan_json}\n```"
        )

    def _extract_fix(self, result: ValidationResult, raw_output: str) -> dict | None:
        fix = result.proposed_fix
        if isinstance(fix, dict) and fix:
            return fix
        if isinstance(fix, str):
            try:
                parsed = json.loads(fix)
                if isinstance(parsed, dict) and parsed:
                    return parsed
            except (json.JSONDecodeError, ValueError):
                pass
        return None
