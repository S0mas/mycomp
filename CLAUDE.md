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
  models.py         dataclasses: Skill, Person, Team, Task, ProjectPlan, CompanyState,
                    SubRequirement, Requirement, RequirementTest, RequirementTestSuite,
                    RequirementsEvaluation, Message, Session, SessionRules + build_prompt()
  llm_backend.py    LLMBackend protocol (transport) + Reasoner protocol (agent brain, with setup() + think())
  reasoner.py       LLMReasoner + create_reasoner() factory + build_system_prompt() / build_user_prompt() helpers
  backends/         provider implementations (anthropic, openai, fake, chat_session). chat_session_backend also contains ChatSessionReasoner
  communication.py  Session management, message routing, communication patterns:
                    lead_delegates | pair_review | develop_test_review
  llm.py            stateless LLM calls (evaluation, autofix, HR). Prompts from prompts/. extract_json_block() utility.
  prompts/          eval_system.txt, autofix_system.txt, hr_system.txt
  workflow.py       multi-step business logic: evaluate_and_gate, plan_and_create_project.
                    CTO planning runs via the same Reasoner/Session infrastructure as all other agents.
  seeds.py          CTO team (cto + cto_analyst) + shared skills (incl. testing). All dev teams created by HR on demand.
  registry.py       all YAML file I/O. save_* auto-registers in state.yaml.
                    Also: save/load requirements, RequirementTestSuites, RequirementTests.
  orchestrator.py   execution loop + topological sort + requirement context injection
  oversight.py      human checkpoint (Approve/Reject/Modify)
  validation.py     input validation (requirements, CTO plans, HR responses)
  cli.py            Click commands — thin UI layer, delegates to workflow.py and orchestrator.py
  mcp_server.py     FastMCP server exposing file/shell tools to Claude agents (run via scripts/start_mcp.sh)
tests/              pytest suite — 239 tests, all mocked (fake_mcp_server.py — MCP reference impl)
docs/               VISION.md, ARCHITECTURE.md, SELF_IMPROVEMENT.md
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
- `workflow.py` owns multi-step business logic (evaluation gate, CTO planning, HR team creation)
- `seeds.py` owns default data definitions — pure data, no I/O
- `cli.py` is a thin UI layer — delegates to `workflow.py` and `orchestrator.py`
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
   - `models.py` — pure data only. No I/O, no API calls, no imports from other aicompany modules.
   - `registry.py` — the ONLY module that reads/writes files. Note: save_* auto-registers in state.yaml.
   - `llm.py` — stateless LLM calls for evaluation, autofix, HR. CTO planning uses the Reasoner/Session path, not llm.py. Prompts live in `prompts/*.txt`.
   - `llm_backend.py` — protocol definition only. No business logic.
   - `reasoner.py` — LLMReasoner + shared prompt-builder helpers. `ChatSessionReasoner` lives in `backends/chat_session_backend.py`. Uses LLMBackend, never concrete providers.
   - `backends/` — provider implementations. Each must call `register_backend()`.
   - `workflow.py` — multi-step business logic. No UI/CLI code.
   - `seeds.py` — default data definitions. Pure data, no I/O.
   - `validation.py` — pure validation logic. No I/O, no LLM calls.
   - `cli.py` — user-facing commands. Thin UI layer — delegates to workflow.py and orchestrator.py.

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

