import uuid
from pathlib import Path

import click
import yaml

from . import config, orchestrator, registry
from .models import CompanyState, Person, ProjectPlan, RequirementsEvaluation, Skill, Task, Team
from .seeds import default_skills, default_teams
from .validation import ValidationError, validate_requirements_text, validate_cto_plan, validate_hr_response
from .workflow import autofix_requirements, evaluate_and_gate, plan_and_create_project


def _print_ok(msg: str) -> None:
    click.echo(click.style(f"✓ {msg}", fg="green"))


def _print_info(msg: str) -> None:
    click.echo(click.style(f"  {msg}", fg="cyan"))


def _print_warn(msg: str) -> None:
    click.echo(click.style(f"! {msg}", fg="yellow"))


def _print_err(msg: str) -> None:
    click.echo(click.style(f"✗ {msg}", fg="red"), err=True)


# ── init ───────────────────────────────────────────────────────────────────────

def _seed_skills(skills: list[Skill]) -> None:
    for s in skills:
        registry.save_skill(s)


def _seed_team(persons: list[Person], team: Team) -> None:
    for p in persons:
        registry.save_person(p)
    registry.save_team(team)


@click.command("init")
def cmd_init():
    """Bootstrap the company: create state.yaml and seed starter skills and teams."""
    if config.STATE_FILE.exists():
        _print_warn("Company already initialised. Delete company/state.yaml to reset.")
        return

    registry.save_state(CompanyState())
    _print_ok("Created company/state.yaml")

    skills = default_skills()
    _seed_skills(skills)
    _print_ok(f"Created {len(skills)} shared skills")

    for persons, team in default_teams():
        _seed_team(persons, team)
        member_roles = " + ".join(p.role for p in persons)
        _print_ok(f"Created {team.id} ({member_roles})")

    click.echo()
    _print_ok("Company ready. Configure your LLM backend and run:")
    click.echo("    python main.py new-project <requirements.md>")


# ── new-project ────────────────────────────────────────────────────────────────

def _score_color(score: int) -> str:
    if score >= 4:
        return "green"
    elif score >= 3:
        return "yellow"
    return "red"


def _print_evaluation(ev: RequirementsEvaluation) -> None:
    click.echo()
    click.echo(click.style("  ── Requirements Evaluation ──", bold=True))
    for label, score in [("Clarity", ev.clarity), ("Completeness", ev.completeness), ("Feasibility", ev.feasibility)]:
        bar = "█" * score + "░" * (5 - score)
        click.echo(click.style(f"  {label:>14}: {bar} {score}/5", fg=_score_color(score)))
    click.echo(click.style(f"  {'Overall':>14}: {ev.overall_score:.1f}/5", bold=True))
    click.echo()
    click.echo(f"  Summary: {ev.summary}")
    if ev.has_risks:
        click.echo(click.style("  Risks:", fg="yellow"))
        for r in ev.risks:
            click.echo(click.style(f"    • {r}", fg="yellow"))
    if ev.suggestions:
        click.echo(click.style("  Suggestions:", fg="cyan"))
        for s in ev.suggestions:
            click.echo(click.style(f"    • {s}", fg="cyan"))
    verdict_color = {"proceed": "green", "needs_work": "yellow", "reject": "red"}.get(ev.verdict, "white")
    click.echo(click.style(f"  Verdict: {ev.verdict.upper()}", fg=verdict_color, bold=True))


@click.command("new-project")
@click.argument("requirements_file", type=click.Path(exists=True))
def cmd_new_project(requirements_file: str):
    """Analyse a requirements file, build teams, and create a project plan."""
    req_path = Path(requirements_file)
    requirements_text = req_path.read_text(encoding="utf-8")

    # ── Sanity checks ─────────────────────────────────────────────────────────
    errors = validate_requirements_text(requirements_text)
    if errors:
        for e in errors:
            _print_err(e)
        raise SystemExit(1)

    click.echo(f"\nAnalysing requirements: {req_path.name}")

    state = registry.load_state()
    state_yaml = yaml.dump(state.to_dict(), default_flow_style=False)

    # ── Evaluate requirements ─────────────────────────────────────────────────
    click.echo("  → Evaluating requirements quality...")
    result = evaluate_and_gate(requirements_text, state_yaml)
    _print_evaluation(result.evaluation)

    # ── Hard block on critical gaps ───────────────────────────────────────────
    if result.blocked:
        click.echo()
        _print_err("Cannot proceed — critical gaps in requirements:")
        for b in result.blockers:
            click.echo()
            _print_err(f"  • {b}")

        if result.evaluation.has_risks:
            click.echo()
            _print_warn("Identified risks:")
            for r in result.evaluation.risks:
                _print_warn(f"    ‣ {r}")

        if result.evaluation.suggestions:
            click.echo()
            _print_info("Suggestions from evaluation:")
            for s in result.evaluation.suggestions:
                _print_info(f"    ‣ {s}")

        # ── Offer autofix ─────────────────────────────────────────────────────
        click.echo()
        if click.confirm(click.style(
            "Would you like AI to auto-fix the requirements?", fg="cyan"
        )):
            click.echo("  → Generating improved requirements...")
            fixed_text = autofix_requirements(
                requirements_text, result.evaluation.to_dict(),
            )
            fixed_path = req_path.with_stem(req_path.stem + "_fixed")
            fixed_path.write_text(fixed_text, encoding="utf-8")
            click.echo()
            _print_ok(f"Improved requirements saved to: {fixed_path}")
            _print_info("Review the file, then re-run:")
            _print_info(f"    python main.py new-project {fixed_path}")
        else:
            click.echo()
            _print_info(f"Fix the requirements manually and re-run:")
            _print_info(f"    python main.py new-project {requirements_file}")

        raise SystemExit(1)

    _print_ok("Requirements passed evaluation — proceeding.")

    # ── CTO planning + HR + project creation ──────────────────────────────────
    plan_result = plan_and_create_project(
        requirements_text, state_yaml,
        on_status=lambda msg: click.echo(f"  → {msg}"),
    )

    if plan_result.plan_warnings:
        _print_warn("CTO plan has issues:")
        for e in plan_result.plan_warnings:
            _print_err(f"  {e}")
        _print_warn("Proceeding with best-effort plan...")

    for team_id, warnings in plan_result.hr_warnings.items():
        _print_warn(f"HR response for '{team_id}' has issues:")
        for w in warnings:
            _print_err(f"    {w}")
        _print_warn("Proceeding with best-effort team...")

    plan = plan_result.plan
    click.echo(f"  → Plan: \"{plan.title}\"")
    click.echo(f"  → Tech stack: {', '.join(plan.tech_stack)}")
    click.echo(f"  → Teams needed: {', '.join(plan.teams_required)}")
    click.echo(f"  → Tasks: {len(plan.tasks)}")

    if plan_result.created_teams:
        for tid in plan_result.created_teams:
            _print_ok(f"  Created team: {tid}")

    click.echo()
    _print_ok(f"Project created: {plan_result.project_id}")
    _print_info(f"Plan: projects/{plan_result.project_id}/plan.yaml")
    click.echo()
    click.echo("Review the plan, then run:")
    click.echo(f"    python main.py run {plan_result.project_id}")


# ── run ────────────────────────────────────────────────────────────────────────

@click.command("run")
@click.argument("project_id")
@click.option("--dry-run", is_flag=True, help="Print each task (id, title, team, deps) that would run — no LLM calls or file writes.")
def cmd_run(project_id: str, dry_run: bool):
    """Execute a project's task plan (with human checkpoints)."""
    try:
        orchestrator.run_project(project_id, dry_run=dry_run)
    except orchestrator.OrchestratorError as e:
        _print_err(str(e))
        raise SystemExit(1)


# ── status ─────────────────────────────────────────────────────────────────────

@click.command("status")
@click.argument("project_id", required=False)
def cmd_status(project_id: str | None):
    """Show task statuses for a project (or list all projects)."""
    if not project_id:
        projects = registry.list_projects()
        if not projects:
            click.echo("No projects found.")
            return
        click.echo("Projects:")
        for pid in projects:
            try:
                plan = registry.load_plan(pid)
                done = sum(1 for t in plan.tasks if t.status == "done")
                total = len(plan.tasks)
                click.echo(f"  {pid}  [{plan.status}]  {plan.title}  ({done}/{total} tasks)")
            except Exception:
                click.echo(f"  {pid}  [unreadable]")
        return

    plan = registry.load_plan(project_id)
    click.echo(f"\nProject: {plan.title} ({plan.project_id})")
    click.echo(f"Status: {plan.status}")
    click.echo(f"Tech: {', '.join(plan.tech_stack)}")
    click.echo()
    click.echo("Tasks:")

    _status_color = {"done": "green", "failed": "red", "running": "yellow", "pending": "white"}
    for t in plan.tasks:
        color = _status_color.get(t.status, "white")
        checkpoint_marker = " [CHECKPOINT]" if t.is_checkpoint else ""
        deps = f" (deps: {', '.join(t.depends_on)})" if t.depends_on else ""
        click.echo(click.style(
            f"  {t.id}  [{t.status}]  {t.title}{checkpoint_marker}{deps}", fg=color
        ))


# ── purge ──────────────────────────────────────────────────────────────────────

@click.command("purge")
@click.option("--all", "purge_all", is_flag=True, help="Also remove .venv/ for a full clean slate.")
@click.confirmation_option(prompt="This will delete all company state and projects. Continue?")
def cmd_purge(purge_all: bool):
    """Delete all runtime state (company/ and projects/). Does not touch .venv/ unless --all."""
    import shutil

    removed = []
    for path in [config.COMPANY_DIR, config.PROJECTS_DIR]:
        if path.exists():
            shutil.rmtree(path)
            removed.append(str(path.relative_to(config.BASE_DIR)))

    venv = config.BASE_DIR / ".venv"
    if purge_all and venv.exists():
        shutil.rmtree(venv)
        removed.append(".venv")

    if removed:
        for r in removed:
            _print_ok(f"Removed: {r}/")
    else:
        _print_info("Nothing to remove — already clean.")

    click.echo()
    if purge_all:
        _print_info("Run ./mycomp init to start fresh (will reinstall dependencies).")
    else:
        _print_info("Run ./mycomp init to reinitialise the company.")


# ── root group ─────────────────────────────────────────────────────────────────

@click.group()
def cli():
    """AI Company — an AI-driven end-to-end software development workflow.

    Typical flow:

    \b
      ./mycomp init                        Bootstrap company state (run once)
      ./mycomp new-project <req.md>        Evaluate requirements, build teams, create plan
      ./mycomp run <project-id>            Execute the plan (human checkpoints included)
      ./mycomp status [project-id]         Check task progress
      ./mycomp purge                       Reset all state and start over
    """
    pass


cli.add_command(cmd_init, "init")
cli.add_command(cmd_new_project, "new-project")
cli.add_command(cmd_run, "run")
cli.add_command(cmd_status, "status")
cli.add_command(cmd_purge, "purge")
