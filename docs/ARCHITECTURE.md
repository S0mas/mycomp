# Architecture — Current Implementation

## Directory Structure

```
mycomp/
│
├── main.py                        # CLI entry point — imports and delegates to aicompany/cli.py
├── requirements.txt               # Python dependencies
├── system-deps.txt                # OS-level dependencies (apt packages)
├── Dockerfile                     # 3-stage container build
├── .env.example                   # Template for required environment variables
│
├── aicompany/                     # Core package — all business logic lives here
│   ├── __init__.py
│   ├── config.py                  # Paths, env vars, model constant
│   ├── models.py                  # Dataclasses: Team, Task, ProjectPlan, CompanyState
│   ├── registry.py                # All file I/O — reads and writes YAML/Markdown
│   ├── llm.py                     # All Claude API calls — CTO, HR, team agents
│   ├── orchestrator.py            # Project execution loop
│   ├── oversight.py               # Human checkpoint: Approve / Reject / Modify
│   └── cli.py                     # Click commands: init, new-project, run, status
│
├── company/                       # Runtime — gitignored, created by `init`
│   ├── state.yaml                 # Company registry (all teams + technologies seen)
│   └── teams/
│       ├── backend_engineer.yaml  # Seeded by init
│       ├── frontend_engineer.yaml # Seeded by init
│       └── *.yaml                 # Created by HR agent on demand
│
├── projects/                      # Runtime — gitignored, created per project
│   └── {project-id}/
│       ├── requirements.md        # Original input copied in at project creation
│       ├── plan.yaml              # CTO-generated structured plan
│       ├── decisions/             # One .md file per human checkpoint
│       └── outputs/               # One .md file per completed task
│
├── tests/
│   ├── conftest.py                # Shared fixtures — filesystem isolation, model factories
│   ├── test_models.py             # Dataclass round-trip and property tests
│   ├── test_registry.py           # YAML I/O tests using tmp directories
│   ├── test_llm_parser.py         # JSON extraction tests
│   ├── test_orchestrator.py       # Topological sort + execution logic tests
│   └── test_cli.py                # CLI command tests with mocked LLM
│
└── docs/
    ├── VISION.md                  # Project goals, principles, and roadmap
    └── ARCHITECTURE.md            # This file
```

---

## Data Models

All models live in `aicompany/models.py`. They are plain Python dataclasses with `from_dict` / `to_dict` methods for YAML serialisation.

### `Team`
Represents one AI agent role in the company registry.

```
id              str       snake_case identifier (e.g. backend_engineer)
name            str       Human-readable label
skills          list[str] Skill tags used for task assignment
system_prompt   str       Full system prompt fed to Claude when this team executes a task
tools           list      Reserved for future tool definitions
context_notes   str       Optional background context prepended at runtime
created_at      str       ISO 8601 UTC timestamp
```

### `CompanyState`
The master registry — one file at `company/state.yaml`.

```
version             str       Schema version
created_at          str       ISO 8601 UTC timestamp
teams               list      Slim team entries: {id, name, skills} — full configs in teams/*.yaml
technologies_seen   list[str] Accumulated across all projects
```

### `Task`
One unit of work within a project plan.

```
id              str         Sequential ID: task_001, task_002, ...
title           str         Short description
description     str         Full instructions for the team agent
assigned_team   str         Team ID that will execute this task
depends_on      list[str]   Task IDs that must complete first
status          str         pending | running | done | failed
is_checkpoint   bool        If true, pause for human approval before executing
output_file     str         Relative path to the task's output Markdown file
```

### `ProjectPlan`
The full plan for one project — lives at `projects/{id}/plan.yaml`.

```
project_id      str         Unique ID: proj_{8 hex chars}
title           str         Project title from CTO analysis
created_at      str         ISO 8601 UTC timestamp
status          str         pending | running | paused | complete | failed
tech_stack      list[str]   Technologies identified by the CTO
teams_required  list[str]   Team IDs needed for this project
tasks           list[Task]  All tasks in dependency order
decisions_log   list        Runtime record of human checkpoint decisions
```

---

## Module Responsibilities

### `config.py`
Defines all filesystem paths and runtime constants. Every other module imports from here — nothing else hardcodes paths. Changing the directory layout is a one-file edit.

Key values:
- `BASE_DIR` — project root (parent of the `aicompany/` package)
- `STATE_FILE` — `company/state.yaml`
- `TEAMS_DIR` — `company/teams/`
- `PROJECTS_DIR` — `projects/`
- `MODEL` — Claude model ID, overridable via `AICOMPANY_MODEL` env var

### `models.py`
Pure data — no I/O, no API calls. All dataclasses have two class/instance methods:
- `from_dict(d)` — construct from a raw dict (as loaded by `yaml.safe_load`)
- `to_dict()` — convert to a plain dict (ready for `yaml.dump`)

Helper properties worth knowing:
- `Team.skill_set` — lowercase set of skills, used for case-insensitive matching
- `CompanyState.all_skills()` — union of all team skill sets
- `CompanyState.team_ids()` — list of all registered team IDs
- `ProjectPlan.task_by_id(id)` — lookup a task by ID, returns `None` if not found

### `registry.py`
All YAML and Markdown file I/O. No logic beyond reading and writing — deliberately thin. Every function has a single responsibility.

Company functions: `load_state`, `save_state`, `load_team`, `save_team`, `find_missing_skills`, `find_team_for_skill`

Project functions: `create_project_dir`, `load_plan`, `save_plan`, `save_output`, `load_output`, `save_decision`, `list_projects`

Side-effect to know: `save_team` also updates `state.yaml` automatically — it keeps the slim team entry in the registry in sync with the full team YAML file.

### `llm.py`
The only module that talks to Claude. Three public functions, one private helper:

| Function | Role | Output |
|---|---|---|
| `cto_analyze(requirements, state_yaml)` | CTO | Plan dict |
| `hr_create_team(skill_name, tech_context)` | HR / Team Builder | Team dict |
| `team_execute_task(system_prompt, title, description, context)` | Team agent | Markdown string |
| `_extract_json_block(text)` | Internal | Parsed dict from a ```json fence |

CTO and HR calls ask Claude to return **only a ```json block** — no prose. `_extract_json_block` finds and parses it, with fallbacks for bare fences and raw JSON.

Team agent calls return raw Markdown — no parsing needed. The output is saved directly as a `.md` file.

### `orchestrator.py`
The execution engine. Entry point is `run_project(project_id, dry_run=False)`.

Execution flow:
1. Load plan from `registry`
2. Topological sort all tasks (`_topological_sort` — Kahn's algorithm)
3. Build `completed_ids` from already-done tasks (crash-safe re-entry)
4. For each task in order:
   - Skip if already done
   - Skip (and mark failed) if a dependency failed or was rejected
   - Raise `OrchestratorError` if dependency is unsatisfied for any other reason
   - If `is_checkpoint` and not dry-run: call `oversight.checkpoint()`
   - If dry-run: print and add to `completed_ids`, then continue
   - Load team, call `llm.team_execute_task()`
   - Save output, mark task done, save plan (crash-safe — persisted after every task)
5. Mark plan `complete` when all tasks are done or failed

### `oversight.py`
Human-in-the-loop. Called by the orchestrator for checkpoint tasks. Displays context in the terminal and waits for a keypress.

Three outcomes:
- **Approved** — task executes unchanged
- **Rejected** — task marked failed; its dependents are also skipped
- **Modified** — user types override instructions; these are appended to the task description before execution

Decision records are written to `projects/{id}/decisions/{timestamp}_{task_id}.md` before the task executes, providing an audit trail even if the process crashes.

Uses `rich` for formatted terminal output if available; falls back to plain `print`/`input` if not installed.

### `cli.py`
Click command group. Thin wiring layer — no business logic. Each command does:

| Command | What it does |
|---|---|
| `init` | Creates `company/state.yaml`, seeds `backend_engineer` and `frontend_engineer` teams |
| `new-project <file>` | Reads requirements → CTO analysis → HR for missing teams → saves project plan |
| `run <project-id>` | Delegates to `orchestrator.run_project()` |
| `run --dry-run <id>` | Same but with `dry_run=True` — no LLM calls, no checkpoints |
| `status` | Lists all projects with task counts |
| `status <id>` | Shows per-task status for one project, highlights checkpoints |

---

## Data Flow

```
User
  │
  │  requirements.md
  ▼
[new-project]
  │
  ├─► llm.cto_analyze()          → plan dict
  │       Claude (CTO role)
  │
  ├─► registry.find_missing_skills()
  │
  ├─► llm.hr_create_team()       → team dict    (for each missing skill)
  │       Claude (HR role)
  │
  ├─► registry.save_team()       → company/teams/{id}.yaml
  │                                 company/state.yaml (synced)
  │
  └─► registry.save_plan()       → projects/{id}/plan.yaml
                                    projects/{id}/requirements.md

[run]
  │
  └─► orchestrator.run_project()
        │
        ├── topological_sort(tasks)
        │
        └── for each task:
              │
              ├── [if checkpoint] oversight.checkpoint()
              │       User: Approve / Reject / Modify
              │       → projects/{id}/decisions/{ts}_{task_id}.md
              │
              ├── registry.load_team()
              │
              ├── llm.team_execute_task()
              │       Claude (team's system_prompt)
              │
              └── registry.save_output()     → projects/{id}/outputs/{task_id}.md
                  registry.save_plan()       → status updated after every task
```

---

## Dependency Layers

```
┌─────────────────────────────────────┐
│           CLI (cli.py)              │  User-facing commands
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│  Orchestrator + Oversight           │  Execution logic
│  (orchestrator.py, oversight.py)    │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│  LLM  (llm.py)                      │  All Claude API calls
│  Registry (registry.py)             │  All file I/O
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│  Models (models.py)                 │  Pure data — no side effects
│  Config (config.py)                 │  Paths and constants
└─────────────────────────────────────┘
```

Each layer only imports from layers below it. `models.py` and `config.py` import nothing from the package.

---

## Environment Variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | — | Claude API authentication |
| `AICOMPANY_MODEL` | No | `claude-sonnet-4-6` | Override the Claude model used |

---

## Dependency Layers for Containerisation

| Layer | File | What it lists |
|---|---|---|
| OS / system | `system-deps.txt` | apt packages (python3.10, python3.10-venv, pip) |
| Python | `requirements.txt` | Python packages (anthropic, PyYAML, click, rich, pytest, pytest-mock) |
| Container | `Dockerfile` | Combines both layers into a 3-stage build |

The `Dockerfile` mounts `company/` and `projects/` as volumes so runtime state persists across container restarts.

---

## Test Strategy

All tests run without a real API key — LLM calls are mocked using `unittest.mock.patch`.

| File | What it tests |
|---|---|
| `test_models.py` | Dataclass construction, round-trips, helper properties |
| `test_registry.py` | YAML read/write, skill matching, project directory structure |
| `test_llm_parser.py` | `_extract_json_block` — the most fragile part of the LLM pipeline |
| `test_orchestrator.py` | Topological sort, execution loop, checkpoint handling, crash recovery |
| `test_cli.py` | CLI commands end-to-end with mocked LLM and filesystem isolation |

`conftest.py` provides an `isolated_fs` fixture (autouse) that redirects all config paths to a fresh `tmp_path` for every test, ensuring tests never touch the real `company/` or `projects/` directories.

Run the suite:
```bash
.venv/bin/pytest tests/ -v
```
