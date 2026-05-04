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
- `AICOMPANY_MCP_SERVERS` — optional, JSON array of MCP server objects for the Anthropic backend (default: `[]`, MCP disabled)
  - Example: `[{"type":"url","url":"https://<tunnel>.trycloudflare.com/mcp","name":"mycomp"}]`
  - Start the MCP server: `./scripts/start_mcp.sh` (starts server + cloudflare tunnel, prints public URL)

---

## Key Commands

```bash
# Run tests (no API key needed — all LLM calls mocked)
.venv/bin/pytest tests/ -v

# Bootstrap company (run once)
.venv/bin/python main.py init

# Start a project
.venv/bin/python main.py new-project path/to/requirements.md

# Preview execution plan (no LLM calls)
.venv/bin/python main.py run --dry-run <project-id>

# Run a project
.venv/bin/python main.py run <project-id>

# Check status
.venv/bin/python main.py status
.venv/bin/python main.py status <project-id>
```

---

## Git & GitHub

- Branch: `main`
- Remote: `https://github.com/S0mas/mycomp.git`
- Push requires `GITHUB_PAT` env var (set in `.claude/settings.local.json`, never committed)
- **No co-author lines in commits** — user preference
- Commit style: imperative subject line, blank line, then body explaining the why

---

## Project Structure

```
aicompany/          core package
  config.py         paths + env vars + backend selection
  models.py         dataclasses (Skill, Person, Team, Task, ProjectPlan, CompanyState, RequirementsEvaluation, Message, Session, SessionRules) + build_prompt()
  llm_backend.py    LLMBackend protocol (transport) + Reasoner protocol (agent brain, with setup() + think())
  reasoner.py       LLMReasoner + ChatSessionReasoner + create_reasoner() factory
  backends/         provider implementations (anthropic, openai, fake, chat_session)
  communication.py  Session management, message routing, communication patterns (lead_delegates, pair_review)
  llm.py            stateless LLM calls via backend (CTO / HR / evaluation — NOT team execution). Loads prompts from prompts/
  prompts/          system prompt templates (cto_system.txt, eval_system.txt, autofix_system.txt, hr_system.txt)
  workflow.py       multi-step business logic (evaluate_and_gate, plan_and_create_project) — extracted from CLI
  seeds.py          default skills, persons, and teams for init — pure data, no I/O
  registry.py       all YAML file I/O (skills, persons, teams, plans, outputs). Note: save_* functions auto-register new IDs in state.yaml
  orchestrator.py   execution loop + topological sort + session-based team coordination
  oversight.py      human checkpoint (Approve/Reject/Modify)
  validation.py     input validation (requirements, CTO plans, HR responses)
  cli.py            Click commands — thin UI layer, delegates to workflow.py and orchestrator.py
  mcp_server.py     FastMCP server exposing file/shell tools to Claude agents (run via scripts/start_mcp.sh)
tests/              pytest suite — 200 tests, all mocked
docs/               VISION.md, ARCHITECTURE.md, SELF_IMPROVEMENT.md
company/            runtime state — gitignored, created by init
  state.yaml        teams + persons + skills + technologies_seen
  skills/           one YAML per shared skill (python, fastapi, etc.)
  persons/          one YAML per person (identity, skills refs, knowledge, rules)
  teams/            one YAML per team (members, lead_id)
projects/           runtime project data — gitignored
  <project_id>/
    plan.yaml         project plan + task statuses
    requirements.md   original requirements text
    outputs/          one .md per task — final agent output
    sessions/         one .json per task — full message log (all agent exchanges)
    decisions/        human checkpoint decisions
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
   - `llm.py` — the ONLY module that calls LLM backends. Never import a provider SDK here. Prompts live in `prompts/*.txt`.
   - `llm_backend.py` — protocol definition only. No business logic.
   - `reasoner.py` — Reasoner implementations (LLMReasoner, ChatSessionReasoner). Uses LLMBackend, never concrete providers.
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

