import json
import os
from contextvars import ContextVar
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent

COMPANY_DIR = BASE_DIR / "company"
STATE_FILE = COMPANY_DIR / "state.yaml"
TEAMS_DIR = COMPANY_DIR / "teams"
SKILLS_DIR = COMPANY_DIR / "skills"
PROJECTS_DIR = BASE_DIR / "projects"

MODEL = os.environ.get("AICOMPANY_MODEL", "claude-sonnet-4-6")
LLM_BACKEND = os.environ.get("AICOMPANY_LLM_BACKEND", "anthropic")
MCP_SERVERS: list[dict] = json.loads(os.environ.get("AICOMPANY_MCP_SERVERS", "[]"))

MAX_TOKENS_CTO = 4096
MAX_TOKENS_HR = 2048
MAX_TOKENS_TEAM = 8096
MAX_TOKENS_EVAL = 2048

MIN_REQUIREMENTS_LENGTH = 50   # characters — below this, reject as too vague
MIN_SCORE_TO_PROCEED = 3.5    # overall score below this → hard block, cannot proceed
MIN_DIMENSION_SCORE = 3       # any single dimension below this → hard block
MAX_TOKENS_AUTOFIX = 4096     # token budget for requirements autofix

LLM_RETRY_ATTEMPTS: int = int(os.environ.get("AICOMPANY_LLM_RETRY_ATTEMPTS", "3"))
LLM_RETRY_BACKOFF_BASE: float = float(os.environ.get("AICOMPANY_LLM_RETRY_BACKOFF_BASE", "2.0"))

# Per-task log callback — set by orchestrator before each task, read by backends/reasoner.
# Signature: (level: str, message: str) -> None
task_log: ContextVar = ContextVar("task_log", default=None)

# Timeouts are defined in anthropic_backend.py and read from env there:
#   AICOMPANY_API_TIMEOUT      — plain calls, default 120s
#   AICOMPANY_API_TIMEOUT_MCP  — MCP calls (many tool round-trips), default 300s
