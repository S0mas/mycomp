import asyncio
from pathlib import Path

import click

from . import config, orchestrator, registry
from .models import CompanyState, Person, Skill, Team
from .seeds import default_skills, default_teams, default_requirements_policy
from .validation import validate_requirements_text
from .planning import plan_and_create_project
from .evaluation import evaluate_requirements


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

    policy_file = config.REQUIREMENTS_POLICY_FILE
    policy_file.write_text(default_requirements_policy(), encoding="utf-8")
    _print_ok(f"Created requirements policy: {policy_file.relative_to(config.BASE_DIR)}")

    click.echo()
    _print_ok("Company ready. Run:")
    click.echo("    python main.py new-project <requirements.md>")


# ── new-project ────────────────────────────────────────────────────────────────

@click.command("new-project")
@click.argument("requirements_file", type=click.Path(exists=True))
def cmd_new_project(requirements_file: str):
    """Analyse requirements, build teams, and create a project plan."""
    requirements_text = Path(requirements_file).read_text(encoding="utf-8")

    errors = validate_requirements_text(requirements_text)
    if errors:
        for e in errors:
            _print_err(e)
        raise SystemExit(1)

    click.echo(f"\nPlanning project from: {Path(requirements_file).name}")

    async def _run():
        click.echo("  → Evaluating requirements against company policy...")
        eval_result = await evaluate_requirements(requirements_text)
        if eval_result.verdict == "reject":
            _print_err(f"Requirements rejected (clarity={eval_result.clarity}, "
                       f"completeness={eval_result.completeness}, "
                       f"feasibility={eval_result.feasibility})")
            if eval_result.violations:
                _print_err("Policy violations:")
                for v in eval_result.violations:
                    _print_err(f"  • {v}")
            if eval_result.suggestions:
                click.echo("Suggestions:")
                for s in eval_result.suggestions:
                    click.echo(f"  • {s}")
            raise SystemExit(1)
        elif eval_result.verdict == "needs_work":
            _print_warn(f"Requirements need improvement: {eval_result.summary}")
            if eval_result.suggestions:
                for s in eval_result.suggestions:
                    _print_warn(f"  • {s}")
            _print_warn("Proceeding anyway — consider revising before running.")
        else:
            _print_ok(f"Requirements approved: {eval_result.summary}")

        return await plan_and_create_project(
            requirements_text,
            on_status=lambda msg: click.echo(f"  → {msg}"),
        )

    plan_result = asyncio.run(_run())

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
@click.option("--dry-run", is_flag=True, help="Print tasks that would run — no agent calls.")
def cmd_run(project_id: str, dry_run: bool):
    """Execute a project's task plan (with human checkpoints)."""
    try:
        asyncio.run(orchestrator.run_project(project_id, dry_run=dry_run))
    except orchestrator.OrchestratorError as e:
        _print_err(str(e))
        raise SystemExit(1)


# ── fail ───────────────────────────────────────────────────────────────────────

@click.command("fail")
@click.argument("project_id")
@click.argument("task_id")
def cmd_fail(project_id: str, task_id: str):
    """Mark a specific task as failed."""
    try:
        plan = registry.load_plan(project_id)
    except FileNotFoundError:
        _print_err(f"Project not found: {project_id}")
        raise SystemExit(1)

    task = plan.task_by_id(task_id)
    if not task:
        _print_err(f"Task not found: {task_id}")
        raise SystemExit(1)

    task.status = "failed"
    registry.save_plan(plan)
    _print_ok(f"{task_id} marked as failed — run './mycomp retry {project_id}' to re-run")


# ── retry ──────────────────────────────────────────────────────────────────────

@click.command("retry")
@click.argument("project_id")
def cmd_retry(project_id: str):
    """Reset all failed tasks to pending and re-run the project."""
    try:
        plan = registry.load_plan(project_id)
    except FileNotFoundError:
        _print_err(f"Project not found: {project_id}")
        raise SystemExit(1)

    failed = [t for t in plan.tasks if t.status == "failed"]
    if not failed:
        _print_info("No failed tasks — nothing to retry.")
        return

    for t in failed:
        t.status = "pending"
    plan.status = "pending"
    registry.save_plan(plan)
    _print_ok(f"Reset {len(failed)} failed task(s) to pending: {', '.join(t.id for t in failed)}")

    try:
        asyncio.run(orchestrator.run_project(project_id))
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

    logs_dir = config.PROJECTS_DIR / project_id / "logs"
    if logs_dir.exists():
        log_files = sorted(logs_dir.glob("*.log"))
        if log_files:
            click.echo()
            click.echo(f"Logs: projects/{project_id}/logs/  ({len(log_files)} task log(s))")

    if plan.decisions_log:
        click.echo()
        click.echo("Checkpoint decisions:")
        _decision_color = {"approved": "green", "modified": "yellow", "rejected": "red"}
        for d in plan.decisions_log:
            color = _decision_color.get(d.get("action", ""), "white")
            click.echo(click.style(
                f"  {d.get('task_id', '?')}  [{d.get('action', '?').upper()}]  {d.get('timestamp', '')}",
                fg=color,
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

    \b
      ./mycomp init                        Bootstrap company state (run once)
      ./mycomp new-project <req.md>        Build teams and create project plan
      ./mycomp run <project-id>            Execute the plan (human checkpoints included)
      ./mycomp retry <project-id>          Reset failed tasks and re-run
      ./mycomp status [project-id]         Check task progress
      ./mycomp purge                       Reset all state and start over
    """
    pass


cli.add_command(cmd_init, "init")
cli.add_command(cmd_new_project, "new-project")
cli.add_command(cmd_run, "run")
cli.add_command(cmd_retry, "retry")
cli.add_command(cmd_status, "status")
cli.add_command(cmd_purge, "purge")
