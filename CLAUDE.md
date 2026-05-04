# mycomp — AI Company

AI-driven SDLC orchestrator. User inputs requirements → CTO plans → HR builds teams → agents execute tasks → human approves checkpoints.

- Vision: [docs/VISION.md](docs/VISION.md)
- Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- GitHub: https://github.com/S0mas/mycomp

---

## Environment

- Python 3.10, virtualenv at `.venv/` — always prefix Python commands with `.venv/bin/`
- `ANTHROPIC_API_KEY` — required for any LLM call
- `AICOMPANY_MODEL` — optional, defaults to `claude-sonnet-4-6`

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
  config.py         paths + env vars
  models.py         dataclasses (Skill, Person, Team, Task, ProjectPlan, CompanyState) + build_prompt()
  registry.py       all YAML file I/O (skills, persons, teams, plans, outputs)
  llm.py            all Claude API calls (CTO / HR / multi-person team execution)
  orchestrator.py   execution loop + topological sort + prompt composition
  oversight.py      human checkpoint (Approve/Reject/Modify)
  cli.py            Click commands
tests/              pytest suite — 100 tests, all mocked
docs/               VISION.md, ARCHITECTURE.md, SELF_IMPROVEMENT.md
company/            runtime state — gitignored, created by init
  state.yaml        teams + persons + skills + technologies_seen
  skills/           one YAML per shared skill (python, fastapi, etc.)
  persons/          one YAML per person (identity, skills refs, knowledge, rules)
  teams/            one YAML per team (members, lead_id)
projects/           runtime project data — gitignored
```

---

## What's Gitignored

- `company/` — runtime state (created by `init`)
- `projects/` — generated per project
- `.venv/` — virtual environment
- `.env`, `.claude/settings.local.json` — secrets

---

## Conventions

- Always run tests before committing: `.venv/bin/pytest tests/ -q`
- Python files only in `aicompany/` — no business logic in `main.py` or `tests/`
- Models are pure data — no I/O or API calls in `models.py`
- `registry.py` is the only module that reads/writes files
- `llm.py` is the only module that calls Claude
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
