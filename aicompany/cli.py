import asyncio
from pathlib import Path

import click
import yaml

from . import config, orchestrator, registry
from .models import CompanyState, Person, Skill, Team
from .planning import plan_and_create_project


def _print_ok(msg: str) -> None:
    click.echo(click.style(f"✓ {msg}", fg="green"))


def _print_info(msg: str) -> None:
    click.echo(click.style(f"  {msg}", fg="cyan"))


def _print_warn(msg: str) -> None:
    click.echo(click.style(f"! {msg}", fg="yellow"))


def _print_err(msg: str) -> None:
    click.echo(click.style(f"✗ {msg}", fg="red"), err=True)


# ── init ───────────────────────────────────────────────────────────────────────

def _build_state_from_disk() -> CompanyState:
    """Scan committed company/ files and build a fresh CompanyState index."""
    state = CompanyState()

    skills_dir = config.SKILLS_DIR
    if skills_dir.exists():
        for path in sorted(skills_dir.glob("*.yaml")):
            with path.open(encoding="utf-8") as f:
                d = yaml.safe_load(f)
            state.skills.append({"id": d["id"], "name": d["name"], "category": d.get("category", "")})

    persons_dir = config.COMPANY_DIR / "persons"
    if persons_dir.exists():
        for path in sorted(persons_dir.glob("*.yaml")):
            with path.open(encoding="utf-8") as f:
                d = yaml.safe_load(f)
            state.persons.append({"id": d["id"], "name": d["name"], "role": d.get("role", "")})

    teams_dir = config.TEAMS_DIR
    if teams_dir.exists():
        for path in sorted(teams_dir.glob("*.yaml")):
            with path.open(encoding="utf-8") as f:
                d = yaml.safe_load(f)
            state.teams.append({"id": d["id"], "name": d["name"], "skills": d.get("skills", [])})

    return state


@click.command("init")
def cmd_init():
    """Initialise runtime state by indexing the committed company defaults."""
    if config.STATE_FILE.exists():
        _print_warn("Company already initialised. Delete company/state.yaml to reset.")
        return

    state = _build_state_from_disk()
    registry.save_state(state)

    _print_ok(f"Indexed {len(state.skills)} skills")
    _print_ok(f"Indexed {len(state.persons)} persons")
    _print_ok(f"Indexed {len(state.teams)} teams")
    click.echo()
    _print_ok("Company ready. Run:")
    click.echo("    python main.py new-project <requirements.md>")


# ── new-project ────────────────────────────────────────────────────────────────

@click.command("new-project")
@click.argument("requirements_file", type=click.Path(exists=True))
def cmd_new_project(requirements_file: str):
    """Analyse requirements, build teams, and create a project plan."""
    requirements_text = Path(requirements_file).read_text(encoding="utf-8")
    if len(requirements_text.strip()) < 50:
        _print_err("Requirements too short (minimum 50 characters).")
        raise SystemExit(1)

    click.echo(f"\nPlanning project from: {Path(requirements_file).name}")

    try:
        plan_result = asyncio.run(plan_and_create_project(
            requirements_text,
            on_status=lambda msg: click.echo(f"  → {msg}"),
        ))
    except Exception as exc:
        _print_err(str(exc))
        raise SystemExit(1)

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
@click.confirmation_option(prompt="This will delete runtime state (state.yaml + projects/). Continue?")
def cmd_purge(purge_all: bool):
    """Delete runtime state (state.yaml and projects/). Committed company defaults are preserved."""
    import shutil

    removed = []

    if config.STATE_FILE.exists():
        config.STATE_FILE.unlink()
        removed.append(str(config.STATE_FILE.relative_to(config.BASE_DIR)))

    if config.PROJECTS_DIR.exists():
        shutil.rmtree(config.PROJECTS_DIR)
        removed.append(str(config.PROJECTS_DIR.relative_to(config.BASE_DIR)))

    venv = config.BASE_DIR / ".venv"
    if purge_all and venv.exists():
        shutil.rmtree(venv)
        removed.append(".venv")

    if removed:
        for r in removed:
            _print_ok(f"Removed: {r}")
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
