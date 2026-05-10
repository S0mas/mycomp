from __future__ import annotations

import json
from typing import Any, Callable

from .. import config
from ..models import Person
from .policy import ValidationPolicy
from .process import ValidationProcess
from .result import ValidationResult


def _check_requirement_refs(plan_dict: dict) -> None:
    """Raise ValueError if any task references a requirement ID not in the plan."""
    valid_ids: set[str] = set()
    for req in plan_dict.get("requirements", []):
        valid_ids.add(req["id"])
        for sub in req.get("sub_requirements", []):
            valid_ids.add(sub["id"])
    errors: list[str] = []
    for task in plan_dict.get("tasks", []):
        bad = [rid for rid in task.get("requirement_ids", []) if rid not in valid_ids]
        if bad:
            errors.append(
                f"task '{task.get('id', '?')}' references unknown requirement IDs: {bad}"
            )
    if errors:
        raise ValueError(
            "Plan contains invalid requirement references:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )

_JSON_RULES = [
    "Output ONLY a ```json block — no prose before or after.",
    'The JSON must have exactly these keys: "verdict" ("approved" or "rejected"), '
    '"summary" (one sentence), "issues" (list of strings), '
    '"suggestions" (list of strings), '
    '"proposed_fix" (the FULL revised plan as a JSON object if rejecting, null if approving).',
    "Set verdict=approved only when the plan is traceable, feasible, and structurally complete.",
    "When rejecting, proposed_fix must be the complete revised plan dict — not a diff.",
    "If '## Structural Issues' appears in the task description, you MUST reject and your "
    "proposed_fix MUST correct every listed structural issue — you cannot approve a plan "
    "that has structural errors.",
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

        structural_section = ""
        try:
            _check_requirement_refs(artifact)
        except ValueError as exc:
            structural_section = (
                f"\n\n## Structural Issues (mandatory — must be corrected in proposed_fix)\n\n"
                f"{exc}\n\n"
                f"Every task's `requirement_ids` must reference an ID that exists in the "
                f"`requirements` list. Correct the offending IDs in your proposed_fix."
            )

        return (
            f"{prefix}Validate the following CTO plan against the plan policy.\n\n"
            f"## Plan Policy\n\n{policy_text}\n\n"
            f"## Plan Under Review\n\n```json\n{plan_json}\n```"
            f"{structural_section}"
        )

    async def run(
        self,
        artifact: Any,
        on_status: Callable[[str], None] | None = None,
    ) -> tuple[Any, Any]:
        result_artifact, result = await super().run(artifact, on_status)
        # Final guard: if AI approved a plan that still has invalid refs, fail hard.
        _check_requirement_refs(result_artifact)
        return result_artifact, result

    def _extract_fix(self, result: ValidationResult, raw_output: str) -> dict | None:
        fix = result.proposed_fix
        if isinstance(fix, dict) and fix:
            try:
                _check_requirement_refs(fix)
            except ValueError:
                return None
            return fix
        if isinstance(fix, str):
            try:
                parsed = json.loads(fix)
                if isinstance(parsed, dict) and parsed:
                    try:
                        _check_requirement_refs(parsed)
                    except ValueError:
                        return None
                    return parsed
            except (json.JSONDecodeError, ValueError):
                pass
        return None
