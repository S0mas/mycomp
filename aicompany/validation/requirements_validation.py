from __future__ import annotations

from typing import Any

from .. import config
from ..models import Person
from .policy import ValidationPolicy
from .process import ValidationProcess
from .result import ValidationResult

_PROPOSAL_FILE = "RequirementsProposal.md"

_JSON_RULES = [
    "Output ONLY a ```json block — no prose before or after.",
    'The JSON must have exactly these keys: "verdict" ("approved" or "rejected"), '
    '"summary" (one sentence), "issues" (list of strings), '
    '"suggestions" (list of strings), "proposed_fix": null.',
    "Set verdict=approved only when requirements fully satisfy the policy.",
    f"When rejecting: you MUST write a COMPLETE revised requirements text to "
    f"`{_PROPOSAL_FILE}` in the workspace BEFORE outputting the JSON. "
    f"The file must be plain text — no JSON encoding. "
    f"Address every issue found. Do not reject without providing a revised version.",
    "When approving: do not write any file.",
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
            f"## Requirements Under Review\n\n{artifact}\n\n"
            f"## Your final output (mandatory)\n\n"
            f"After collecting team feedback you MUST follow your rules:\n"
            f"- If REJECTING: use the Write tool to write the complete revised requirements "
            f"to `{_PROPOSAL_FILE}` first, then output the JSON verdict block.\n"
            f"- If APPROVING: output the JSON verdict block only."
        )

    def _extract_fix(self, result: ValidationResult, raw_output: str) -> str | None:
        proposal_path = config.BASE_DIR / _PROPOSAL_FILE
        if not proposal_path.exists():
            return None
        text = proposal_path.read_text(encoding="utf-8").strip()
        proposal_path.unlink()
        return text if text else None
