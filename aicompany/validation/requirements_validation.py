from __future__ import annotations

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
    '"proposed_fix" (the FULL revised requirements text if rejecting, null if approving).',
    "Set verdict=approved only when requirements fully satisfy the policy.",
    "When rejecting, proposed_fix must be the complete revised requirements text — not a diff.",
]


class RequirementsValidation(ValidationProcess):
    """Validates requirements text against requirements_policy.md.

    Team: technical analyst + quality reviewer (different perspectives).
    Lead synthesises their feedback into a structured verdict with optional fix.
    """

    _max_attempts = 3

    _lead = Person(
        id="req_val_lead",
        name="Requirements Validation Lead",
        role="lead",
        identity=(
            "You are a senior requirements analyst leading a validation panel. "
            "You synthesise your team's multi-perspective feedback and produce a "
            "structured verdict on whether requirements meet the company policy."
        ),
        knowledge=["requirements engineering", "policy compliance review"],
        rules=_JSON_RULES,
    )

    _validators = [
        Person(
            id="req_val_tech",
            name="Technical Analyst",
            role="reviewer",
            identity=(
                "You are a technical analyst who evaluates requirements for "
                "feasibility, precision, named actors, and implementation clarity. "
                "Flag ambiguous success criteria and undefined external dependencies."
            ),
            knowledge=["software architecture", "API design", "feasibility analysis"],
            rules=["Focus on technical clarity, implementability, and named actors."],
        ),
        Person(
            id="req_val_quality",
            name="Quality Reviewer",
            role="reviewer",
            identity=(
                "You are a QA specialist who evaluates requirements for completeness, "
                "testability, and policy compliance. Verify that acceptance criteria "
                "follow Given/When/Then format and are measurable."
            ),
            knowledge=["test engineering", "acceptance criteria", "policy compliance"],
            rules=["Focus on completeness, testability, and policy violations."],
        ),
    ]

    @property
    def policy(self) -> ValidationPolicy:
        return ValidationPolicy.from_path(config.REQUIREMENTS_POLICY_FILE)

    def _build_task_description(self, artifact: str, attempt: int) -> str:
        policy_text = self.policy.load()
        prefix = f"[Attempt {attempt}] " if attempt > 1 else ""
        return (
            f"{prefix}Validate the following requirements text against the policy.\n\n"
            f"## Requirements Policy\n\n{policy_text}\n\n"
            f"## Requirements Under Review\n\n{artifact}"
        )

    def _extract_fix(self, result: ValidationResult) -> str | None:
        fix = result.proposed_fix
        if isinstance(fix, str) and fix.strip():
            return fix
        return None
