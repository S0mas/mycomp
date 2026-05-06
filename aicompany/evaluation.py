"""
Requirements evaluation gate.

Stateless: receives requirements text, calls LLM, returns a structured result
indicating whether planning can proceed and what needs to be improved.
"""
from __future__ import annotations

import yaml

from . import config, llm, registry
from .models import RequirementsEvaluation

_FIX_HINTS = {
    "Clarity": (
        "Break vague statements into specific, testable requirements. "
        "Replace 'should handle many users' with 'must support 1000 concurrent connections'."
    ),
    "Completeness": (
        "Add missing sections: acceptance criteria, error handling, "
        "authentication, deployment constraints, data model, API contracts."
    ),
    "Feasibility": (
        "Reduce scope to a realistic first iteration. Split into phases. "
        "Remove dependencies on unavailable technologies or unrealistic timelines."
    ),
}


class EvaluationResult:
    """Outcome of the requirements evaluation gate."""

    def __init__(
        self,
        evaluation: RequirementsEvaluation,
        blockers: list[str],
        fix_hints: dict[str, str],
    ) -> None:
        self.evaluation = evaluation
        self.blockers = blockers
        self.fix_hints = fix_hints

    @property
    def blocked(self) -> bool:
        return bool(self.blockers)


def evaluate_and_gate(requirements_text: str) -> EvaluationResult:
    """
    Evaluate requirements quality and determine if planning can proceed.
    Returns an EvaluationResult with the evaluation and any blockers.
    """
    state = registry.load_state()
    state_yaml = yaml.dump(state.to_dict(), default_flow_style=False)
    evaluation = RequirementsEvaluation.from_dict(
        llm.evaluate_requirements(requirements_text, state_yaml)
    )

    blockers: list[str] = []

    if evaluation.overall_score < config.MIN_SCORE_TO_PROCEED:
        blockers.append(
            f"Overall score {evaluation.overall_score:.1f}/5 is below minimum "
            f"{config.MIN_SCORE_TO_PROCEED}. The requirements need significant improvement."
        )

    for label, score in [
        ("Clarity", evaluation.clarity),
        ("Completeness", evaluation.completeness),
        ("Feasibility", evaluation.feasibility),
    ]:
        if score < config.MIN_DIMENSION_SCORE:
            blockers.append(
                f"{label} scored {score}/5 (minimum {config.MIN_DIMENSION_SCORE}). "
                f"Fix: {_FIX_HINTS[label]}"
            )

    if evaluation.verdict == "reject":
        blockers.append(
            "Evaluation verdict is REJECT — the input is fundamentally unsuitable. "
            "Ensure it describes a software project with clear deliverables."
        )

    return EvaluationResult(evaluation, blockers, _FIX_HINTS)


def autofix_requirements(requirements_text: str, eval_dict: dict) -> str:
    """Delegate to LLM to rewrite requirements. Returns improved text."""
    return llm.autofix_requirements(requirements_text, eval_dict)
