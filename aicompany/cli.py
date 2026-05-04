import uuid
from datetime import datetime, timezone
from pathlib import Path

import click
import yaml

from . import config, llm, orchestrator, registry
from .models import CompanyState, ProjectPlan, Task, Team


def _print_ok(msg: str) -> None:
    click.echo(click.style(f"✓ {msg}", fg="green"))


def _print_info(msg: str) -> None:
    click.echo(click.style(f"  {msg}", fg="cyan"))


def _print_warn(msg: str) -> None:
    click.echo(click.style(f"! {msg}", fg="yellow"))


def _print_err(msg: str) -> None:
    click.echo(click.style(f"✗ {msg}", fg="red"), err=True)


# ── init ───────────────────────────────────────────────────────────────────────

@click.command("init")
def cmd_init():
    """Bootstrap the company: create state.yaml and seed starter teams."""
    if config.STATE_FILE.exists():
        _print_warn("Company already initialised. Delete company/state.yaml to reset.")
        return

    state = CompanyState()
    registry.save_state(state)
    _print_ok("Created company/state.yaml")

    # Seed backend team
    backend = Team(
        id="backend_engineer",
        name="Backend Engineer",
        skills=["python", "rest_api", "fastapi", "sqlalchemy", "postgresql", "docker"],
        system_prompt=(
            "You are a senior backend engineer at an AI software company. "
            "You write clean, production-quality Python code.\n\n"
            "You prefer FastAPI for APIs, SQLAlchemy for ORM, PostgreSQL for databases, "
            "and Docker for containerisation.\n\n"
            "When asked to implement a feature or task, produce:\n"
            "1. All necessary file paths with their complete code\n"
            "2. Any configuration or environment variable requirements\n"
            "3. A brief explanation of key design decisions\n\n"
            "Format your output as Markdown with fenced code blocks "
            "using appropriate language tags (e.g. ```python, ```yaml)."
        ),
    )
    registry.save_team(backend)
    _print_ok("Created company/teams/backend_engineer.yaml")

    # Seed frontend team
    frontend = Team(
        id="frontend_engineer",
        name="Frontend Engineer",
        skills=["react", "typescript", "nextjs", "tailwind", "html", "css"],
        system_prompt=(
            "You are a senior frontend engineer at an AI software company. "
            "You build modern, accessible web interfaces.\n\n"
            "You prefer React with TypeScript, Next.js for SSR/SSG, "
            "and Tailwind CSS for styling.\n\n"
            "When asked to implement a feature or UI component, produce:\n"
            "1. All necessary file paths with their complete code\n"
            "2. Component structure and prop types\n"
            "3. A brief explanation of UX and accessibility decisions\n\n"
            "Format your output as Markdown with fenced code blocks."
        ),
    )
    registry.save_team(frontend)
    _print_ok("Created company/teams/frontend_engineer.yaml")

    click.echo()
    _print_ok("Company ready. Set ANTHROPIC_API_KEY and run:")
    click.echo("    python main.py new-project <requirements.md>")


# ── new-project ────────────────────────────────────────────────────────────────

@click.command("new-project")
@click.argument("requirements_file", type=click.Path(exists=True))
def cmd_new_project(requirements_file: str):
    """Analyse a requirements file, build teams, and create a project plan."""
    req_path = Path(requirements_file)
    requirements_text = req_path.read_text(encoding="utf-8")

    click.echo(f"\nAnalysing requirements: {req_path.name}")

    # Load current company state
    state = registry.load_state()
    state_yaml = yaml.dump(state.to_dict(), default_flow_style=False)

    # CTO analyses requirements
    click.echo("  → CTO is analysing requirements...")
    plan_dict = llm.cto_analyze(requirements_text, state_yaml)

    title = plan_dict.get("title", "Untitled Project")
    tech_stack = plan_dict.get("tech_stack", [])
    teams_required = plan_dict.get("teams_required", [])
    raw_tasks = plan_dict.get("tasks", [])

    click.echo(f"  → Plan: \"{title}\"")
    click.echo(f"  → Tech stack: {', '.join(tech_stack)}")
    click.echo(f"  → Teams needed: {', '.join(teams_required)}")
    click.echo(f"  → Tasks: {len(raw_tasks)}")

    # Check for missing skills / teams
    missing_team_ids = [tid for tid in teams_required if tid not in state.team_ids()]
    if missing_team_ids:
        click.echo()
        click.echo(f"  Creating {len(missing_team_ids)} missing team(s)...")

    for team_id in missing_team_ids:
        _print_warn(f"  Team '{team_id}' not found — HR is creating it...")
        tech_context = ", ".join(tech_stack)
        team_dict = llm.hr_create_team(team_id, tech_context)
        # Ensure the id matches what the CTO requested
        team_dict["id"] = team_id
        team = Team.from_dict(team_dict)
        registry.save_team(team)
        _print_ok(f"  Created team: {team.name} ({team.id})")

        # Update technologies_seen
        state = registry.load_state()

    # Update technologies_seen in state
    state = registry.load_state()
    for tech in tech_stack:
        if tech.lower() not in [t.lower() for t in state.technologies_seen]:
            state.technologies_seen.append(tech)
    registry.save_state(state)

    # Build Project
    project_id = f"proj_{uuid.uuid4().hex[:8]}"
    tasks = []
    for i, raw in enumerate(raw_tasks):
        task_id = raw.get("id", f"task_{i+1:03d}")
        output_file = f"outputs/{task_id}.md"
        tasks.append(Task(
            id=task_id,
            title=raw["title"],
            description=raw["description"],
            assigned_team=raw["assigned_team"],
            depends_on=raw.get("depends_on", []),
            is_checkpoint=raw.get("is_checkpoint", False),
            output_file=output_file,
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

    click.echo()
    _print_ok(f"Project created: {project_id}")
    _print_info(f"Plan: projects/{project_id}/plan.yaml")
    click.echo()
    click.echo("Review the plan, then run:")
    click.echo(f"    python main.py run {project_id}")


# ── run ────────────────────────────────────────────────────────────────────────

@click.command("run")
@click.argument("project_id")
@click.option("--dry-run", is_flag=True, help="Show what would execute without calling the LLM.")
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

    _status_color = {
        "done": "green",
        "failed": "red",
        "running": "yellow",
        "pending": "white",
    }

    for t in plan.tasks:
        color = _status_color.get(t.status, "white")
        checkpoint_marker = " [CHECKPOINT]" if t.is_checkpoint else ""
        deps = f" (deps: {', '.join(t.depends_on)})" if t.depends_on else ""
        line = f"  {t.id}  [{t.status}]  {t.title}{checkpoint_marker}{deps}"
        click.echo(click.style(line, fg=color))


# ── root group ─────────────────────────────────────────────────────────────────

@click.group()
def cli():
    """AI Company — an AI-driven end-to-end software development workflow."""
    pass


cli.add_command(cmd_init, "init")
cli.add_command(cmd_new_project, "new-project")
cli.add_command(cmd_run, "run")
cli.add_command(cmd_status, "status")
