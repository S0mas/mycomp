import uuid
from pathlib import Path

import click
import yaml

from . import config, llm, orchestrator, registry
from .models import CompanyState, Person, ProjectPlan, RequirementsEvaluation, Skill, Task, Team
from .validation import ValidationError, validate_requirements_text, validate_cto_plan, validate_hr_response


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

    # ── Shared skills ─────────────────────────────────────────────────────────
    skills = [
        Skill(id="python", name="Python", category="language", knowledge=[
            "Use type hints on all function signatures",
            "Prefer pathlib over os.path for file operations",
            "Use dataclasses or Pydantic for structured data",
            "Follow PEP 8 naming conventions",
        ]),
        Skill(id="fastapi", name="FastAPI", category="framework", knowledge=[
            "Use async def for route handlers",
            "Use Pydantic models for request/response validation",
            "Use Depends() for dependency injection",
            "Always set response_model for automatic serialization",
        ]),
        Skill(id="sqlalchemy", name="SQLAlchemy", category="framework", knowledge=[
            "Use SQLAlchemy 2.0 select() style, not legacy Query",
            "Define models with mapped_column() for type safety",
            "Use sessionmaker with context managers for transaction safety",
        ]),
        Skill(id="postgresql", name="PostgreSQL", category="tool", knowledge=[
            "Use migrations (Alembic) for schema changes — never raw DDL in code",
            "Add indexes on foreign keys and frequently filtered columns",
        ]),
        Skill(id="docker", name="Docker", category="tool", knowledge=[
            "Use multi-stage builds to minimize image size",
            "Never store secrets in image layers",
            "Pin base image versions for reproducibility",
        ]),
        Skill(id="react", name="React", category="framework", knowledge=[
            "Use functional components with hooks, not class components",
            "Prefer controlled components for form inputs",
            "Use React.memo() and useMemo() only when profiling shows a need",
        ]),
        Skill(id="typescript", name="TypeScript", category="language", knowledge=[
            "Always define explicit types for function parameters and return values",
            "Use interfaces for object shapes and type aliases for unions",
            "Avoid 'any' — use 'unknown' and narrow with type guards",
        ]),
        Skill(id="nextjs", name="Next.js", category="framework", knowledge=[
            "Use app router (app/) not pages router for new projects",
            "Use server components by default, add 'use client' only when needed",
            "Use next/image for automatic image optimization",
        ]),
        Skill(id="tailwind", name="Tailwind CSS", category="framework", knowledge=[
            "Use utility classes directly — avoid @apply in most cases",
            "Use the design system (spacing, colors) consistently",
        ]),
        Skill(id="rest_api", name="REST API Design", category="practice", knowledge=[
            "Use proper HTTP methods: GET for reads, POST for creates, PUT/PATCH for updates",
            "Return appropriate status codes: 201 for created, 404 for not found, 422 for validation errors",
            "Version APIs in the URL path: /api/v1/",
        ]),
        Skill(id="html", name="HTML", category="language", knowledge=[
            "Use semantic elements (header, main, nav, section) not just divs",
            "Always include alt text on images",
        ]),
        Skill(id="css", name="CSS", category="language", knowledge=[
            "Use flexbox and grid for layout, not floats",
            "Use CSS custom properties (variables) for theming",
        ]),
    ]
    _seed_skills(skills)
    _print_ok(f"Created {len(skills)} shared skills")

    # ── Backend team ──────────────────────────────────────────────────────────
    backend_lead = Person(
        id="backend_lead",
        name="Backend Tech Lead",
        role="lead",
        identity="You are a Backend Tech Lead at an AI software company.",
        skills=["python", "fastapi", "sqlalchemy", "postgresql", "docker", "rest_api"],
        knowledge=[
            "You plan backend work, assign sub-tasks to your team, and synthesize their outputs",
            "Your team specialises in Python, FastAPI, SQLAlchemy, PostgreSQL, and Docker",
        ],
        rules=[
            "When writing a brief: be concise, name each member explicitly, and state exactly what they should produce",
            "When synthesizing: resolve conflicts, deduplicate, and produce one coherent Markdown document with all file paths and code",
        ],
    )
    backend_coder = Person(
        id="backend_coder",
        name="Backend Engineer",
        role="coder",
        identity="You are a senior Backend Engineer specialising in Python.",
        skills=["python", "fastapi", "sqlalchemy", "postgresql"],
        knowledge=[],
        rules=[
            "For every task, produce complete file paths with full code in fenced ```python blocks",
            "Include any required environment variables or config",
            "Include one-line explanation of key design decisions",
            "No placeholders. No TODOs. Complete, runnable code only",
        ],
    )
    backend_reviewer = Person(
        id="backend_reviewer",
        name="Backend Code Reviewer",
        role="reviewer",
        identity="You are a Backend Code Reviewer.",
        skills=["python", "fastapi", "sqlalchemy"],
        knowledge=[
            "Your job is to review code produced by your team and flag issues before synthesis",
        ],
        rules=[
            "For each piece of code, check: correctness (logic errors, edge cases), security (SQL injection, hardcoded secrets, missing validation), style (naming, function size, duplication), test coverage gaps",
            "Produce a Markdown review with: issues found (with file + line), suggested fixes, and a final verdict (approve / request changes)",
        ],
    )
    backend_team = Team(
        id="backend_team",
        name="Backend Team",
        skills=["python", "rest_api", "fastapi", "sqlalchemy", "postgresql", "docker"],
        members=["backend_lead", "backend_coder", "backend_reviewer"],
        lead_id="backend_lead",
    )
    _seed_team([backend_lead, backend_coder, backend_reviewer], backend_team)
    _print_ok("Created backend_team (lead + coder + reviewer)")

    # ── Frontend team ─────────────────────────────────────────────────────────
    frontend_lead = Person(
        id="frontend_lead",
        name="Frontend Tech Lead",
        role="lead",
        identity="You are a Frontend Tech Lead.",
        skills=["react", "typescript", "nextjs", "tailwind", "html", "css"],
        knowledge=[
            "You plan UI work, assign sub-tasks, and synthesize outputs",
            "Your team uses React, TypeScript, Next.js, and Tailwind CSS",
        ],
        rules=[
            "When writing a brief: name each member, state what component/file they own",
            "When synthesizing: produce one coherent Markdown document with all components and styles",
        ],
    )
    frontend_coder = Person(
        id="frontend_coder",
        name="Frontend Engineer",
        role="coder",
        identity="You are a senior Frontend Engineer specialising in React and TypeScript.",
        skills=["react", "typescript", "nextjs", "tailwind", "html", "css"],
        knowledge=[],
        rules=[
            "For every task, produce complete file paths with full code in fenced ```tsx or ```ts blocks",
            "Include prop types and component interfaces",
            "Include accessibility considerations",
            "No placeholders. Complete, renderable components only",
        ],
    )
    frontend_team = Team(
        id="frontend_team",
        name="Frontend Team",
        skills=["react", "typescript", "nextjs", "tailwind", "html", "css"],
        members=["frontend_lead", "frontend_coder"],
        lead_id="frontend_lead",
    )
    _seed_team([frontend_lead, frontend_coder], frontend_team)
    _print_ok("Created frontend_team (lead + coder)")

    click.echo()
    _print_ok("Company ready. Set ANTHROPIC_API_KEY and run:")
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
    eval_dict = llm.evaluate_requirements(requirements_text, state_yaml)
    evaluation = RequirementsEvaluation.from_dict(eval_dict)

    _print_evaluation(evaluation)

    # ── Hard block on critical gaps ───────────────────────────────────────────
    blockers = []
    if evaluation.overall_score < config.MIN_SCORE_TO_PROCEED:
        blockers.append(
            f"Overall score {evaluation.overall_score:.1f} is below minimum "
            f"{config.MIN_SCORE_TO_PROCEED}."
        )
    for label, score in [("Clarity", evaluation.clarity),
                         ("Completeness", evaluation.completeness),
                         ("Feasibility", evaluation.feasibility)]:
        if score < config.MIN_DIMENSION_SCORE:
            blockers.append(
                f"{label} score {score}/5 is below minimum "
                f"{config.MIN_DIMENSION_SCORE}."
            )
    if evaluation.verdict == "reject":
        blockers.append("Evaluation verdict is REJECT.")

    if blockers:
        click.echo()
        _print_err("Cannot proceed — critical gaps in requirements:")
        for b in blockers:
            _print_err(f"  • {b}")
        click.echo()
        _print_info(f"Fix the requirements and re-run:  python main.py new-project {requirements_file}")
        raise SystemExit(1)

    while True:
        choice = click.prompt(
            click.style("\n[P]roceed / [E]dit requirements / [C]ancel", fg="cyan"),
            type=click.Choice(["p", "e", "c", "P", "E", "C"], case_sensitive=False),
            show_choices=False,
        ).lower()

        if choice == "c":
            _print_warn("Cancelled by user.")
            return
        elif choice == "e":
            _print_info(f"Edit the file and re-run:  python main.py new-project {requirements_file}")
            return
        elif choice == "p":
            break

    # ── CTO planning ──────────────────────────────────────────────────────────
    click.echo("  → CTO is analysing requirements...")
    plan_dict = llm.cto_analyze(requirements_text, state_yaml)

    plan_errors = validate_cto_plan(plan_dict)
    if plan_errors:
        _print_warn("CTO plan has issues:")
        for e in plan_errors:
            _print_err(f"  {e}")
        _print_warn("Proceeding with best-effort plan...")

    title = plan_dict.get("title", "Untitled Project")
    tech_stack = plan_dict.get("tech_stack", [])
    teams_required = plan_dict.get("teams_required", [])
    raw_tasks = plan_dict.get("tasks", [])

    click.echo(f"  → Plan: \"{title}\"")
    click.echo(f"  → Tech stack: {', '.join(tech_stack)}")
    click.echo(f"  → Teams needed: {', '.join(teams_required)}")
    click.echo(f"  → Tasks: {len(raw_tasks)}")

    missing_team_ids = [tid for tid in teams_required if tid not in state.team_ids()]
    if missing_team_ids:
        click.echo()
        click.echo(f"  Creating {len(missing_team_ids)} missing team(s)...")

    for team_id in missing_team_ids:
        _print_warn(f"  Team '{team_id}' not found — HR is creating it...")
        tech_context = ", ".join(tech_stack)
        result = llm.hr_create_team(team_id, tech_context)

        # HR returns {"team": {...}, "persons": [...], "skills": [...]}
        team_data = result.get("team", result)
        persons_data = result.get("persons", [])
        skills_data = result.get("skills", [])

        hr_errors = validate_hr_response(result, team_id)
        if hr_errors:
            _print_warn(f"  HR response for '{team_id}' has issues:")
            for e in hr_errors:
                _print_err(f"    {e}")
            _print_warn("  Proceeding with best-effort team...")

        team_data["id"] = team_id
        team = Team.from_dict(team_data)

        for sd in skills_data:
            registry.save_skill(Skill.from_dict(sd))
        for pd in persons_data:
            registry.save_person(Person.from_dict(pd))
        registry.save_team(team)

        _print_ok(f"  Created team: {team.name} with {len(persons_data)} person(s)")
        state = registry.load_state()

    state = registry.load_state()
    for tech in tech_stack:
        if tech.lower() not in [t.lower() for t in state.technologies_seen]:
            state.technologies_seen.append(tech)
    registry.save_state(state)

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

    _status_color = {"done": "green", "failed": "red", "running": "yellow", "pending": "white"}
    for t in plan.tasks:
        color = _status_color.get(t.status, "white")
        checkpoint_marker = " [CHECKPOINT]" if t.is_checkpoint else ""
        deps = f" (deps: {', '.join(t.depends_on)})" if t.depends_on else ""
        click.echo(click.style(
            f"  {t.id}  [{t.status}]  {t.title}{checkpoint_marker}{deps}", fg=color
        ))


# ── root group ─────────────────────────────────────────────────────────────────

@click.group()
def cli():
    """AI Company — an AI-driven end-to-end software development workflow."""
    pass


cli.add_command(cmd_init, "init")
cli.add_command(cmd_new_project, "new-project")
cli.add_command(cmd_run, "run")
cli.add_command(cmd_status, "status")
