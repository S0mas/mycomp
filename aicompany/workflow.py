"""
Workflow logic for project creation.

Extracted from cli.py to follow SRP — the CLI handles user interaction,
this module owns the multi-step business logic for evaluating requirements,
CTO planning, HR team creation, and project assembly.
"""
from __future__ import annotations

import uuid

from . import config, llm, registry
from .models import (
    CompanyState, Person, ProjectPlan, RequirementsEvaluation,
    Skill, Task, Team,
)
from .validation import validate_cto_plan, validate_hr_response


# ── Requirements evaluation ───────────────────────────────────────────────────

class EvaluationResult:
    """Outcome of the evaluation gate."""

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
        return len(self.blockers) > 0


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


def evaluate_and_gate(requirements_text: str, state_yaml: str) -> EvaluationResult:
    """
    Evaluate requirements quality and determine if planning can proceed.

    Returns an EvaluationResult with the evaluation and any blockers.
    """
    eval_dict = llm.evaluate_requirements(requirements_text, state_yaml)
    evaluation = RequirementsEvaluation.from_dict(eval_dict)

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


# ── CTO planning + HR team creation + project assembly ───────────────────────

class PlanResult:
    """Outcome of CTO planning + HR team creation."""

    def __init__(
        self,
        project_id: str,
        plan: ProjectPlan,
        plan_warnings: list[str],
        created_teams: list[str],
        hr_warnings: dict[str, list[str]],
    ) -> None:
        self.project_id = project_id
        self.plan = plan
        self.plan_warnings = plan_warnings
        self.created_teams = created_teams
        self.hr_warnings = hr_warnings


def plan_and_create_project(
    requirements_text: str,
    state_yaml: str,
    on_status: callable = None,
) -> PlanResult:
    """
    Run CTO analysis, create missing teams via HR, assemble and persist the project.

    Args:
        requirements_text: The requirements document.
        state_yaml: Current company state as YAML string.
        on_status: Optional callback for progress messages.

    Returns a PlanResult with the project plan and metadata.
    """
    _status = on_status or (lambda msg: None)

    # ── CTO planning ──────────────────────────────────────────────────────
    _status("CTO is analysing requirements...")
    plan_dict = llm.cto_analyze(requirements_text, state_yaml)
    plan_warnings = validate_cto_plan(plan_dict)

    title = plan_dict.get("title", "Untitled Project")
    tech_stack = plan_dict.get("tech_stack", [])
    teams_required = plan_dict.get("teams_required", [])
    raw_tasks = plan_dict.get("tasks", [])

    # ── HR team creation ──────────────────────────────────────────────────
    state = registry.load_state()
    missing_team_ids = [tid for tid in teams_required if tid not in state.team_ids()]
    created_teams: list[str] = []
    hr_warnings: dict[str, list[str]] = {}

    for team_id in missing_team_ids:
        _status(f"Team '{team_id}' not found — HR is creating it...")
        tech_context = ", ".join(tech_stack)
        result = llm.hr_create_team(team_id, tech_context)

        team_data = result.get("team", result)
        persons_data = result.get("persons", [])
        skills_data = result.get("skills", [])

        errors = validate_hr_response(result, team_id)
        if errors:
            hr_warnings[team_id] = errors

        team_data["id"] = team_id
        team = Team.from_dict(team_data)

        for sd in skills_data:
            registry.save_skill(Skill.from_dict(sd))
        for pd in persons_data:
            registry.save_person(Person.from_dict(pd))
        registry.save_team(team)

        created_teams.append(team_id)
        state = registry.load_state()

    # ── Update technologies_seen ──────────────────────────────────────────
    state = registry.load_state()
    for tech in tech_stack:
        if tech.lower() not in [t.lower() for t in state.technologies_seen]:
            state.technologies_seen.append(tech)
    registry.save_state(state)

    # ── Assemble project ──────────────────────────────────────────────────
    project_id = f"proj_{uuid.uuid4().hex[:8]}"
    tasks = []
    for i, raw in enumerate(raw_tasks):
        task_id = raw.get("id", f"task_{i+1:03d}")
        tasks.append(Task(
            id=task_id,
            title=raw["title"],
            description=raw["description"],
            assigned_team=raw["assigned_team"],
            depends_on=raw.get("depends_on", []),
            is_checkpoint=raw.get("is_checkpoint", False),
            output_file=f"outputs/{task_id}.md",
        ))

    plan = ProjectPlan(
        project_id=project_id,
        title=title,
        tech_stack=tech_stack,
        teams_required=teams_required,
        tasks=tasks,
    )

    registry.create_project_dir(project_id, requirements_text)
    registry.save_plan(plan)

    return PlanResult(
        project_id=project_id,
        plan=plan,
        plan_warnings=plan_warnings,
        created_teams=created_teams,
        hr_warnings=hr_warnings,
    )
