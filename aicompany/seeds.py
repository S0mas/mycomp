"""
Seed data for company initialisation.

Contains the default skills and the CTO team created on `init`.
All development teams are created on demand by HR during project planning.
"""
from .models import Person, Skill, Team

# JSON schema embedded in the CTO's rules so it survives in the Person definition
_CTO_JSON_SCHEMA = '''
Output ONLY a ```json block with EXACTLY this schema — no prose before or after:

```json
{
  "title": "Short project title (max 60 chars)",
  "tech_stack": ["technology1", "technology2"],
  "teams_required": ["team_id1"],
  "requirements": [
    {
      "id": "REQ-0001",
      "title": "Requirement title",
      "description": "What the user needs.",
      "sub_requirements": [
        {
          "id": "REQ-0001-001",
          "title": "Sub-requirement title",
          "description": "Specific, testable slice of the requirement.",
          "acceptance_criteria": [
            "Given X, when Y, then Z"
          ]
        }
      ]
    }
  ],
  "tasks": [
    {
      "id": "task_001",
      "title": "Task title",
      "description": "Detailed description of what to build and expected output.",
      "assigned_team": "team_id",
      "depends_on": [],
      "is_checkpoint": false,
      "requirement_ids": ["REQ-0001-001"]
    }
  ]
}
```'''


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
        Skill(id="testing", name="Requirements Testing", category="practice", knowledge=[
            "Requirement tests prove USER REQUIREMENTS are met — not internal code logic",
            "Name test functions: test_REQ_XXXX_NNN_short_description",
            "Each test must have a docstring: Requirement: <id>\\nAcceptance: <criterion>",
            "Write tests from the user's perspective (API endpoints, observable behaviour)",
            "Use arrange-act-assert pattern; shared fixtures go in conftest.py",
            "Save test files to: tests/requirements/test_<req_id>.py in the workspace",
        ]),
    ]


def default_teams() -> list[tuple[list[Person], Team]]:
    """
    Return the starter teams seeded on init.

    Only the CTO team is seeded. All development teams are created on demand
    by HR when the CTO requests them during project planning.
    """
    cto = Person(
        id="cto",
        name="CTO",
        role="lead",
        identity=(
            "You are the CTO of an AI-driven software company. "
            "Your job is to analyse client requirements and produce a precise, "
            "structured project plan together with a full requirements decomposition. "
            "You have access to the company's current team registry. "
            "Reuse existing team IDs where their skills match — only list teams in "
            "`teams_required` that are genuinely needed."
        ),
        skills=[],
        knowledge=[
            "Decompose every big requirement into specific, testable sub-requirements",
            "Every sub-requirement must have concrete acceptance_criteria",
            "Every task must reference the sub-requirement IDs it implements via requirement_ids",
            "Keep tasks focused: one team, one session, 4–10 tasks total",
        ],
        rules=[
            "Output ONLY a ```json block — no prose before or after" + _CTO_JSON_SCHEMA,
            "task IDs: task_001, task_002, ... (sequential)",
            "REQ IDs: REQ-0001, REQ-0002, ... (sequential per project)",
            "Sub-requirement IDs: REQ-0001-001, REQ-0001-002, ...",
            "team IDs: snake_case (e.g. backend_team, frontend_team)",
            "Reuse existing team IDs from the registry when their skills match",
            "Mark is_checkpoint: true for deployment, payment, security config, or irreversible production actions",
            "depends_on lists task IDs that must complete before this task",
        ],
    )

    cto_analyst = Person(
        id="cto_analyst",
        name="Technical Analyst",
        role="reviewer",
        identity=(
            "You are a Technical Analyst supporting the CTO. "
            "Your job is to review project plans for feasibility, coherence, "
            "and completeness of requirements coverage."
        ),
        skills=[],
        knowledge=[
            "A good plan has every requirement traced to at least one task",
            "No task should be orphaned (unrelated to any requirement)",
            "Tech stack must be consistent with the task descriptions",
            "Team IDs must be plausible snake_case identifiers",
        ],
        rules=[
            "Return a Markdown review with: issues found (specific), suggested fixes, "
            "and a final verdict: approve OR request-changes",
            "If you request changes, be precise about which field needs updating",
            "Do NOT rewrite the JSON yourself — only describe what needs to change",
        ],
    )

    cto_team = Team(
        id="cto_team",
        name="CTO Office",
        skills=[],
        members=["cto", "cto_analyst"],
        lead_id="cto",
        communication={"pattern": "pair_review", "max_rounds": 4},
    )

    return [
        ([cto, cto_analyst], cto_team),
    ]
