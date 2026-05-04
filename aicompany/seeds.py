"""
Seed data for company initialisation.

Contains the default skills, persons, and teams that are created when the user
runs `init`. Separated from CLI to follow SRP — the CLI handles interaction,
this module owns the data definitions.
"""
from .models import Person, Skill, Team


def default_skills() -> list[Skill]:
    """Return the starter set of shared skills."""
    return [
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


def default_teams() -> list[tuple[list[Person], Team]]:
    """
    Return the starter teams.

    Each entry is (persons, team) — ready to be persisted by the registry.
    """
    # ── Backend team ──────────────────────────────────────────────────────
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

    # ── Frontend team ─────────────────────────────────────────────────────
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

    return [
        ([backend_lead, backend_coder, backend_reviewer], backend_team),
        ([frontend_lead, frontend_coder], frontend_team),
    ]
