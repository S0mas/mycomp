# mycomp — AI Company

AI-driven SDLC orchestrator. User inputs requirements → CTO plans → HR builds teams → agents execute tasks → human approves checkpoints.

- Vision: [docs/VISION.md](docs/VISION.md)
- Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Backends: [docs/BACKENDS.md](docs/BACKENDS.md)
- GitHub: https://github.com/S0mas/mycomp

---

## Environment

- Python 3.10, virtualenv at `.venv/` — always prefix Python commands with `.venv/bin/`
- `AICOMPANY_MODEL` — optional, defaults to `claude-sonnet-4-6`
- No API key needed in environment — all LLM calls go through the `claude` CLI (Claude Code's own auth)

---

## Key Commands

```bash
# Run tests (no API key needed — all LLM calls mocked)
.venv/bin/pytest tests/ -v

# The ./mycomp wrapper auto-creates .venv and installs deps on first run
./mycomp init                                    # Bootstrap company (run once)
./mycomp new-project path/to/requirements.md     # Plan a project (CTO + HR via agents)
./mycomp run --dry-run <project-id>              # Preview tasks (no LLM calls)
./mycomp run <project-id>                        # Execute project
./mycomp retry <project-id>                      # Reset failed tasks and re-run
./mycomp status                                  # List all projects
./mycomp status <project-id>                     # Task-level status
./mycomp purge                                   # Delete company/ and projects/ (reset)
./mycomp purge --all                             # Also delete .venv/ (full clean slate)
```

---

## Git & GitHub

- Branch: `main`
- Remote: `https://github.com/S0mas/mycomp.git`
- **Auto-push on every commit** — a `PostToolUse` hook in `.claude/settings.local.json` pushes to GitHub automatically after each `git commit`. No manual push needed.
- Push uses `GITHUB_PAT` env var (set in `.claude/settings.local.json`, never committed)
- **No co-author lines in commits** — user preference
- Commit style: imperative subject line, blank line, then body explaining the why

---

## Project Structure

```
mycomp              shell entry-point wrapper — auto-creates .venv, then delegates to main.py
.env.example        env var reference (copy to .env and fill in secrets)
aicompany/          core package
  config.py         paths, MODEL env var, MIN_REQUIREMENTS_LENGTH, task_log ContextVar
  models/           data models — split by domain (all re-exported from models/__init__.py):
    org.py          Skill, Person, Team, CompanyState, build_prompt
    project.py      TaskInput(specification, context), TaskStub, Plan (alias: ProjectPlan), MAX_PLAN_DEPTH
                    TaskInput.specification is validated; context is parent background (never validated).
                    TaskStub: lightweight child entry (id, title, assigned_team, depends_on, depended_on_by,
                    is_checkpoint, status). Plan.tasks: list[TaskStub] — stubs only; full task plans are
                    stored in tasks/{id}/plan.yaml on disk. Plan.has_subtasks=False → leaf, True → composite;
                    to_dict/from_dict depth-bounded at MAX_PLAN_DEPTH=20. Plan.id: project_id at root,
                    task_id at all other depths.
    requirements.py SubRequirement, Requirement, RequirementTest, RequirementTestSuite, RequirementsEvaluation
    session.py      Message, SessionRules, Session
  person_agent.py   PersonAgent: wraps ClaudeSDKClient (claude-code-sdk). One persistent Claude Code process per
                    person per task. Agents keep context across their turns (lead remembers brief when synthesizing,
                    coder remembers implementation when revising). Uses permission_mode="bypassPermissions".
  communication.py  create_session, run_pattern (async, dispatches to patterns.py). Re-exports pattern functions.
  patterns.py       Async pattern implementations: run_lead_delegates, run_pair_review, run_develop_test_review.
                    Each person gets a PersonAgent; multi-turn persons (lead, coder) keep their process alive.
  utils.py          Shared utilities: extract_json_block() — parses ```json fenced blocks or bare JSON.
  validation/       AI-driven quality validation package (multi-agent, policy-driven, fix-retry loop):
    __init__.py     re-exports: ValidationPolicy, ValidationResult, ValidationProcess, ValidationError,
                    RequirementsValidation, PlanValidation
    policy.py       ValidationPolicy — loads .md policy file, lazy-cached, fallback default
    result.py       ValidationResult — parsed from lead JSON output: verdict, issues, proposed_fix
    process.py      ValidationProcess (ABC) + ValidationError — owns the fix-retry loop;
                    uses lead_delegates pattern: lead briefs validators → each reviews → lead synthesises
    requirements_validation.py  RequirementsValidation — 2 validators (tech analyst, quality reviewer);
                    validates requirements text against requirements_policy.md
    plan_validation.py          PlanValidation — 3 validators (architecture, traceability, feasibility);
                    validates CTO plan dict against plan_policy.md
  planning.py       async CTO planning + HR team creation + project assembly + deduplication:
                    PlanResult(project_id, plan, created_teams)
                    Classes: CTOPlanning, HRTeamCreation, Deduplication — each has a .run() method
                    plan_and_create_project: RequirementsValidation → CTOPlanning → PlanValidation →
                    _build_task_tree (recursive, saves tasks/{id}/plan.yaml) → save root plan → Deduplication
                    _build_task_tree: non-leaf tasks (non-empty "subtasks" key) recurse with req-val+CTO+plan-val;
                    leaf tasks get their own plan.yaml. Computes depended_on_by (reverse of depends_on).
  seeds.py          Default data for company/: skills, CTO team+persons, policy text.
                    Used by tests (via _seed_defaults_to_disk) and as fallback reference.
                    CTO schema includes optional "subtasks" key for recursive planning signal.
  registry.py       all YAML file I/O. _load_yaml/_save_yaml helpers. save_* auto-registers in state.yaml.
                    Also: save/load requirements, RequirementTestSuites, RequirementTests.
                    save_task_plan / load_task_plan: nested task plan I/O (BFS search via _find_task_node).
                    Task plans stored at tasks/{id}/plan.yaml inside the project directory tree.
  orchestrator.py   async execution loop + topological sort. _handle_checkpoint, _execute_task (async),
                    run_project (async, called via asyncio.run() from CLI), _execute_subtask_plan.
                    Operates on TaskStub lists (no Task objects). Loads each task's plan via load_task_plan.
                    Teams discover dependency outputs via workspace — no automatic output injection.
  oversight.py      human checkpoint UI: _display_task, _prompt_decision, checkpoint()
  cli.py            Click commands — thin UI layer, delegates to planning.py, orchestrator.py
                    cmd_new_project: inline 50-char length check, then plan_and_create_project (validation embedded).
                    cmd_init: builds state.yaml by scanning committed company/ files (skills, persons, teams).
                              Does NOT write any files — defaults are already in the repo.
tests/              pytest suite — 265 tests, all mocked (no API key needed).
                    Async tests use pytest-asyncio (asyncio_mode=auto in pytest.ini).
                    Pattern/orchestrator tests mock PersonAgent via FakePersonAgent.
                    planning/cli tests patch CTOPlanning, HRTeamCreation, Deduplication, RequirementsValidation, PlanValidation.
docs/               VISION.md, ARCHITECTURE.md, SELF_IMPROVEMENT.md, BACKENDS.md
                    README.md — navigation index for all docs
                    01-overview.md through 10-config.md — structured technical docs with PlantUML diagrams
                    potential_issues.md — deferred issues with design notes
company/            runtime state — gitignored, created by init
  state.yaml        teams + persons + skills + technologies_seen
  skills/           one YAML per shared skill
  persons/          one YAML per person (identity, skills refs, knowledge, rules)
  teams/            one YAML per team (members, lead_id, communication pattern)
projects/           runtime project data — gitignored
  <project_id>/
    plan.yaml           root plan: metadata + TaskStub list
    requirements.md     original requirements text
    tasks/              recursive task plan tree
      <task_id>/
        plan.yaml       task's own plan: input, scoped requirements, sub-task stubs
        tasks/          nested sub-tasks (same structure, recursive)
    src/                live source files written by agents (Claude Code cwd for all PersonAgents)
    outputs/            one .md per task — final agent output
    sessions/           one .json per task — full message log
    decisions/          human checkpoint decisions
    req_tests/          _requirements.yaml + TEST-XXXX-NNN.yaml records
    test_suites/        SUITE-XXXX.yaml — groups RequirementTests per Requirement
```

---

## What's Gitignored

- `company/state.yaml` — runtime index (built by `init` from committed files)
- `projects/` — generated per project
- `.venv/` — virtual environment
- `.env`, `.claude/settings.local.json` — secrets

## What's Committed in `company/`

- `company/skills/*.yaml` — default shared skills (13 built-in)
- `company/persons/cto.yaml`, `company/persons/cto_analyst.yaml` — CTO team persons
- `company/teams/cto_team.yaml` — CTO team definition
- `company/requirements_policy.md` — default requirements quality policy (client-editable)
- `company/plan_policy.md` — default plan quality policy (client-editable)

HR-created teams and persons are also written to `company/` at runtime and can be committed.

---

## Conventions

> **See "Mandatory Rules for AI Contributors" above for the full list.**

- Always run tests before committing: `.venv/bin/pytest tests/ -q`
- Python files only in `aicompany/` — no business logic in `main.py` or `tests/`
- Models are pure data — no I/O or API calls in `models.py`
- `registry.py` is the only module that reads/writes files (save_* auto-registers new IDs in state.yaml)
- `validation/` owns all AI-driven quality gates — ValidationProcess subclasses embed the fix-retry loop
- `planning.py` owns CTO planning, HR team creation, recursive task expansion, and project assembly
- `seeds.py` owns default data definitions — pure data, no I/O
- `cli.py` is a thin UI layer — delegates to `planning.py` and `orchestrator.py`
- No new dependencies without updating `requirements.txt` and `system-deps.txt`
- When adding a new module, add corresponding tests in `tests/`

---

## Testing

All tests are fully isolated — `conftest.py` redirects all config paths to `tmp_path` via `monkeypatch`. LLM calls are mocked with `unittest.mock.patch`. No API key needed.

```bash
.venv/bin/pytest tests/ -v               # full suite
.venv/bin/pytest tests/test_models.py   # single file
.venv/bin/pytest -k "test_round_trip"   # by name pattern
```

---

## Mandatory Rules for AI Contributors

**Every AI agent (Claude, GPT, Copilot, or any other) working on this project MUST follow these rules. No exceptions.**

### Before Making Changes

1. **Read this file first.** It is the single source of truth for project rules.
2. **Understand the architecture.** Read `docs/ARCHITECTURE.md` before touching code. Know which module owns what responsibility.
3. **Check existing tests.** Run `.venv/bin/pytest tests/ -q` to confirm green baseline before starting.

### While Making Changes

4. **Respect module boundaries.**
   - `models/` — pure data only. No I/O, no API calls, no imports from other aicompany modules (except within the package itself).
   - `registry.py` — the ONLY module that reads/writes files. Note: save_* auto-registers in state.yaml.
   - `llm.py` — stateless LLM calls. Prompts live in `prompts/*.txt`.
   - `person_agent.py` — PersonAgent (one ClaudeSDKClient per person per task). No direct LLM calls.
      - `planning.py` — CTO planning, HR creation, project assembly. No CLI/UI code.
   - `planning.py` — CTO planning, HR team creation, project assembly. No UI/CLI code.
   - `patterns.py` — async communication pattern implementations. Creates PersonAgent instances. No direct LLM calls or file I/O.
   - `communication.py` — session creation and pattern dispatch only.
   - `seeds.py` — default data definitions. Pure data, no I/O.
   - `validation.py` — pure validation logic. No I/O, no LLM calls.
   - `cli.py` — user-facing commands. Thin UI layer — delegates to evaluation.py, planning.py, orchestrator.py.

5. **Write tests for every change.** No PR/commit without corresponding test updates.
   - New function → new test
   - Changed behaviour → updated test
   - New module → new test file in `tests/`

6. **Keep tests isolated.** All tests must pass without API keys, network, or filesystem side effects. Use mocks and `isolated_fs` fixtures.

7. **No hardcoded provider dependencies.** Never `import anthropic` or `import openai` outside of `backends/`. All LLM interaction goes through the `LLMBackend` protocol.

### After Making Changes

8. **Run the full test suite.** `.venv/bin/pytest tests/ -q` — all tests must pass.

9. **Update documentation.** If you change behaviour, update the relevant docs:
   - Changed a module → update the Project Structure section in this file
   - Changed environment variables → update Environment section in this file
   - Changed backends → update `docs/BACKENDS.md`
   - Changed architecture → update `docs/ARCHITECTURE.md`
   - Changed test count → update the test count in Project Structure section
   - Added a new command → update Key Commands section in this file

10. **Update the test count.** After adding/removing tests, update the count in the Project Structure section above (currently shows the test count next to `tests/`).

11. **Commit with clear messages.** Imperative subject line, blank line, body explaining what and why. No co-author lines.

12. **Push using `git push origin main`.** Do NOT hardcode tokens in push URLs.

### Things You Must NEVER Do

- ❌ Add business logic to `main.py` — it's just the CLI entrypoint
- ❌ Add direct API calls anywhere — all LLM goes through PersonAgent (patterns) or SDK query() (planning)
- ❌ Import `anthropic` — it is no longer a dependency
- ❌ Skip tests — if you can't test it, don't ship it
- ❌ Commit runtime artifacts (`company/`, `projects/`, `reqs*.md`)
- ❌ Add dependencies without updating `requirements.txt` and `system-deps.txt`
- ❌ Make changes without reading this file first
- ❌ Leave documentation out of date after a change
- ❌ Ask the user to validate something you can validate yourself — run tests, check binaries, verify commands, read files. Do it.

