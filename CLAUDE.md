# mycomp — AI Company

AI-driven SDLC orchestrator. User inputs requirements → CTO plans → HR builds teams → agents execute tasks → human approves checkpoints.

- Vision: [docs/VISION.md](docs/VISION.md)
- Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Backends: [docs/BACKENDS.md](docs/BACKENDS.md)
- GitHub: https://github.com/S0mas/mycomp

---

## Environment

- Python 3.10, virtualenv at `.venv/` — always prefix Python commands with `.venv/bin/`
- `AICOMPANY_LLM_BACKEND` — optional, defaults to `anthropic` (pluggable: any backend implementing `LLMBackend` protocol)
- `AICOMPANY_MODEL` — optional, defaults to `claude-sonnet-4-6`
- `ANTHROPIC_API_KEY` — required when using the `anthropic` backend
- `AICOMPANY_MCP_SERVERS` — **required for `run`**, JSON array of MCP server objects
  - Example: `[{"type":"url","url":"https://<tunnel>.trycloudflare.com/mcp","name":"mycomp"}]`
  - Start the MCP server: `./scripts/start_mcp.sh` (starts server + cloudflare tunnel, prints public URL)
  - Requires `cloudflared` binary in the project root — download from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
  - See `docs/BACKENDS.md` for the required tool interface

---

## Key Commands

```bash
# Run tests (no API key needed — all LLM calls mocked)
.venv/bin/pytest tests/ -v

# The ./mycomp wrapper auto-creates .venv and installs deps on first run
./mycomp init                                    # Bootstrap company (run once)
./mycomp new-project path/to/requirements.md     # Evaluate + plan a project
./mycomp run --dry-run <project-id>              # Preview tasks (no LLM calls)
./mycomp run <project-id>                        # Execute project
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
  config.py         paths + env vars + backend selection
  models/           data models — split by domain (all re-exported from models/__init__.py):
    org.py          Skill, Person, Team, CompanyState, build_prompt
    project.py      TaskInput(specification, context), Task, Plan (alias: ProjectPlan), MAX_PLAN_DEPTH
                    TaskInput.specification is validated; context is parent background (never validated).
                    Task.plan: Plan is ALWAYS present (never None); Plan.has_subtasks=False → leaf,
                    True → composite; to_dict/from_dict depth-bounded at MAX_PLAN_DEPTH=20
    requirements.py SubRequirement, Requirement, RequirementTest, RequirementTestSuite, RequirementsEvaluation
    session.py      Message, SessionRules, Session
  llm_backend.py    LLMBackend protocol (transport) + Reasoner protocol (agent brain, with setup() + think())
  reasoner.py       LLMReasoner + create_reasoner() factory + build_system_prompt() / build_user_prompt() helpers
  backends/         provider implementations (anthropic, openai, fake, chat_session). chat_session_backend also contains ChatSessionReasoner
  communication.py  create_session, run_pattern (dispatches to patterns.py). Re-exports pattern functions.
  patterns.py       Pattern implementations: run_lead_delegates, run_pair_review, run_develop_test_review.
                    _members_by_role helper. _agent_rules session+workspace rule builder.
  llm.py            stateless LLM calls (evaluation, autofix, HR). Prompts from prompts/. extract_json_block() utility.
  prompts/          eval_system.txt, autofix_system.txt, cto_system.txt, hr_system.txt
  evaluation.py     Requirements quality gate: EvaluationResult, evaluate_and_gate, autofix_requirements
  planning.py       CTO planning + HR team creation + project assembly: PlanResult, plan_and_create_project
                    Helpers: _run_cto_planning, _create_missing_teams, _update_technologies, _assemble_project
  seeds.py          CTO team (cto + cto_analyst) + shared skills (incl. testing). All dev teams created by HR on demand.
  registry.py       all YAML file I/O. _load_yaml/_save_yaml helpers. save_* auto-registers in state.yaml.
                    Also: save/load requirements, RequirementTestSuites, RequirementTests.
  orchestrator.py   execution loop + topological sort. _handle_checkpoint, _execute_task, _build_project_context
                    _execute_subtask_plan (recursive sub-task execution), _find_prior_output (all dep outputs)
  oversight.py      human checkpoint UI: _display_task, _prompt_decision, checkpoint()
  validation.py     input validation: validate_requirements_text (delegates to TaskInput.validate()),
                    validate_cto_plan (decomposed into _validate_plan_structure, _validate_tasks,
                    _validate_task_dependencies), validate_hr_response. PATTERN_ROLES set for role validation.
  cli.py            Click commands — thin UI layer, delegates to evaluation.py, planning.py, orchestrator.py
  mcp_server.py     FastMCP server exposing file/shell tools to Claude agents (run via scripts/start_mcp.sh)
tests/              pytest suite — 274 tests, all mocked (fake_mcp_server.py — MCP reference impl)
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
    plan.yaml           project plan + task statuses + embedded requirements
    requirements.md     original requirements text
    src/                live source files written by agents via MCP
    outputs/            one .md per task — final agent output
    sessions/           one .json per task — full message log
    decisions/          human checkpoint decisions
    req_tests/          _requirements.yaml + TEST-XXXX-NNN.yaml records
    test_suites/        SUITE-XXXX.yaml — groups RequirementTests per Requirement
```

---

## What's Gitignored

- `company/` — runtime state (created by `init`)
- `projects/` — generated per project
- `.venv/` — virtual environment
- `.env`, `.claude/settings.local.json` — secrets

---

## Conventions

> **See "Mandatory Rules for AI Contributors" above for the full list.**

- Always run tests before committing: `.venv/bin/pytest tests/ -q`
- Python files only in `aicompany/` — no business logic in `main.py` or `tests/`
- Models are pure data — no I/O or API calls in `models.py`
- `registry.py` is the only module that reads/writes files (save_* auto-registers new IDs in state.yaml)
- `llm.py` is the only module that calls LLM backends (via the `LLMBackend` protocol). Prompts live in `prompts/` as text files
- `evaluation.py` owns the requirements quality gate; `planning.py` owns CTO planning, HR team creation, project assembly
- `seeds.py` owns default data definitions — pure data, no I/O
- `cli.py` is a thin UI layer — delegates to `evaluation.py`, `planning.py`, and `orchestrator.py`
- No hardcoded provider imports outside `backends/`
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
   - `llm_backend.py` — protocol definition only. No business logic.
   - `reasoner.py` — LLMReasoner + shared prompt-builder helpers. `ChatSessionReasoner` lives in `backends/chat_session_backend.py`. Uses LLMBackend, never concrete providers.
   - `backends/` — provider implementations. Each must call `register_backend()`.
   - `evaluation.py` — requirements quality gate only. No team/project creation.
   - `planning.py` — CTO planning, HR team creation, project assembly. No UI/CLI code.
   - `patterns.py` — communication pattern implementations. No direct LLM or file I/O.
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
- ❌ Import provider SDKs in `llm.py` — use the backend abstraction
- ❌ Skip tests — if you can't test it, don't ship it
- ❌ Commit runtime artifacts (`company/`, `projects/`, `reqs*.md`)
- ❌ Add dependencies without updating `requirements.txt` and `system-deps.txt`
- ❌ Make changes without reading this file first
- ❌ Leave documentation out of date after a change

