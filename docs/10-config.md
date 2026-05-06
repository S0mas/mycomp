# Configuration

All configuration lives in `aicompany/config.py`. Values come from environment variables
with sensible defaults.

---

## Environment variables

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `ANTHROPIC_API_KEY` | — | Yes (anthropic backend) | Anthropic API key |
| `AICOMPANY_LLM_BACKEND` | `anthropic` | No | Backend name: `anthropic`, `openai`, `fake`, `chat_session` |
| `AICOMPANY_MODEL` | `claude-sonnet-4-6` | No | Model ID passed to backend |
| `AICOMPANY_MCP_SERVERS` | `[]` | Yes (for `run`) | JSON array of MCP server objects. Example: `[{"type":"url","url":"https://...","name":"mycomp"}]` |
| `OPENAI_API_KEY` | — | Yes (openai backend) | OpenAI API key |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | No | Base URL for OpenAI-compatible APIs (Ollama, LocalAI, etc.) |
| `MYCOMP_CHAT_TIMEOUT` | `600` | No | Seconds to wait for human operator response in chat_session mode |
| `MYCOMP_EXCHANGE_DIR` | `<project_root>/tmp/llm_exchange` | No | Directory for chat_session file handshake |
| `GITHUB_PAT` | — | Auto-push hook only | GitHub Personal Access Token (set in `.claude/settings.local.json`, not committed) |

---

## Filesystem paths

| Constant | Value | Description |
|----------|-------|-------------|
| `BASE_DIR` | `<repo_root>/` | Project root (parent of `aicompany/`) |
| `COMPANY_DIR` | `BASE_DIR/company/` | Runtime company state (gitignored) |
| `STATE_FILE` | `COMPANY_DIR/state.yaml` | CompanyState registry |
| `TEAMS_DIR` | `COMPANY_DIR/teams/` | One YAML per Team |
| `SKILLS_DIR` | `COMPANY_DIR/skills/` | One YAML per Skill |
| `PROJECTS_DIR` | `BASE_DIR/projects/` | One directory per project (gitignored) |

---

## Token budgets

| Constant | Value | Used for |
|----------|-------|---------|
| `MAX_TOKENS_TEAM` | 8,096 | Each agent think() call in task execution |
| `MAX_TOKENS_CTO` | 4,096 | CTO planning session |
| `MAX_TOKENS_HR` | 2,048 | HR team creation |
| `MAX_TOKENS_EVAL` | 2,048 | Requirements evaluation |
| `MAX_TOKENS_AUTOFIX` | 4,096 | Requirements autofix |

---

## Quality gate thresholds

| Constant | Value | Meaning |
|----------|-------|---------|
| `MIN_REQUIREMENTS_LENGTH` | 50 | Minimum character count for requirements text |
| `MIN_SCORE_TO_PROCEED` | 3.5 | Minimum average score across all evaluation dimensions |
| `MIN_DIMENSION_SCORE` | 3 | Minimum score for any single dimension (clarity, completeness, feasibility) |

---

## Retry configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `AICOMPANY_LLM_RETRY_ATTEMPTS` | `3` | Max number of attempts per LLM call (1 = no retry) |
| `AICOMPANY_LLM_RETRY_BACKOFF_BASE` | `2.0` | Exponential backoff base in seconds. Wait after attempt N = `base^N`. Default: 1s, 2s, … |

Applied in both `LLMReasoner.think()` and `llm._call()`. Set `AICOMPANY_LLM_RETRY_ATTEMPTS=1`
to disable retries entirely.

---

## Task recursion limit

`MAX_PLAN_DEPTH = 20` (in `models/project.py`)

Plan/Task serialisation tracks nesting depth via a `_depth` parameter. Raises `ValueError`
if depth exceeds 20 to prevent infinite recursion from malformed data.

---

## Validation role set

`PATTERN_ROLES = {"lead", "coder", "reviewer", "tester"}` (in `validation.py`)

HR responses that include persons with roles outside this set produce validation warnings
(non-blocking), since pattern routing relies on these exact role strings.

---

## `.env.example`

The repo includes `.env.example` with all variables. Copy to `.env` and fill in secrets:

```bash
cp .env.example .env
# Edit .env with your API keys
```

The `.env` file is gitignored. Secrets for the Claude Code auto-push hook are stored in
`.claude/settings.local.json` (also gitignored).
