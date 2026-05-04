# AI Company

An AI-driven end-to-end software development workflow. You provide requirements and a vision — the system plans the project, assembles the right team of AI agents, executes the work, and delivers outputs. It pauses only at decisions that genuinely require human judgement.

```
you → requirements.md → [CTO plans] → [HR builds teams] → [agents execute] → outputs/
                                                                    ↑
                                               human approves checkpoints
```

→ [Vision and roadmap](docs/VISION.md)
→ [Architecture and module reference](docs/ARCHITECTURE.md)

---

## Quick Start

### 1. Install dependencies

```bash
# Create virtual environment
pip install virtualenv
virtualenv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install Python packages
pip install -r requirements.txt
```

### 2. Set your API key

```bash
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY=sk-ant-...
export ANTHROPIC_API_KEY=sk-ant-...
```

### 3. Initialise the company

```bash
python main.py init
```

Creates `company/state.yaml` and seeds two starter teams: `backend_team` (lead + coder + reviewer) and `frontend_team` (lead + coder). Each team is composed of individual AI persons with specialised roles and system prompts.

### 4. Start a project

```bash
python main.py new-project path/to/requirements.md
```

The CTO agent analyses your requirements and produces a plan. If the plan requires skills the company doesn't have yet, the HR agent creates those teams automatically. Prints the project ID when done.

### 5. Review the plan

```bash
cat projects/<project-id>/plan.yaml
```

Edit the plan directly if you want to change task order, assignments, or checkpoint flags before running.

### 6. Run the project

```bash
python main.py run <project-id>
```

Tasks execute in dependency order. At checkpoint tasks the system pauses and asks you to **[A]pprove**, **[R]eject**, or **[M]odify** before continuing.

### 7. Check status

```bash
python main.py status                  # list all projects
python main.py status <project-id>    # per-task breakdown
```

---

## Commands

| Command | Description |
|---|---|
| `python main.py init` | Bootstrap the company (run once) |
| `python main.py new-project <file>` | Analyse requirements and create a project plan |
| `python main.py run <project-id>` | Execute a project with human checkpoints |
| `python main.py run --dry-run <id>` | Preview what would execute — no LLM calls |
| `python main.py status` | List all projects |
| `python main.py status <project-id>` | Show task-level status for one project |

---

## Project Outputs

Every project lives in `projects/<project-id>/`:

```
projects/proj_abc123/
├── requirements.md          # Your original input
├── plan.yaml                # CTO-generated plan (editable before running)
├── decisions/               # Audit log — one file per human checkpoint
│   └── 20260504T103000_task_002.md
└── outputs/                 # Task outputs — one Markdown file per task
    ├── task_001.md
    └── task_002.md
```

---

## Running with Docker

```bash
docker build -t aicompany .

docker run -it \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -v $(pwd)/company:/app/company \
  -v $(pwd)/projects:/app/projects \
  aicompany new-project /app/requirements.md
```

Mounting `company/` and `projects/` as volumes preserves state across runs.

---

## Running Tests

No API key needed — all LLM calls are mocked.

```bash
.venv/bin/pytest tests/ -v
```

83 tests covering models, registry, LLM JSON parsing, orchestrator logic, and CLI commands.

---

## Configuration

| Environment variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | required | Claude API key |
| `AICOMPANY_MODEL` | `claude-sonnet-4-6` | Override the Claude model |

---

## What Gets Committed

Source files tracked in git:

```
aicompany/      Python source
tests/          Test suite
docs/           Documentation
main.py
requirements.txt
system-deps.txt
Dockerfile
.env.example
```

Runtime state excluded from git (in `.gitignore`):

```
company/        Created by init — changes with every project
projects/       Generated at runtime
.venv/          Local virtual environment
.env            Contains secrets
__pycache__/
```
