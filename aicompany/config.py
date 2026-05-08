import os
from contextvars import ContextVar
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent

COMPANY_DIR = BASE_DIR / "company"
STATE_FILE = COMPANY_DIR / "state.yaml"
TEAMS_DIR = COMPANY_DIR / "teams"
SKILLS_DIR = COMPANY_DIR / "skills"
REQUIREMENTS_POLICY_FILE = COMPANY_DIR / "requirements_policy.md"
PLAN_POLICY_FILE = COMPANY_DIR / "plan_policy.md"
PROJECTS_DIR = BASE_DIR / "projects"

MODEL = os.environ.get("AICOMPANY_MODEL", "claude-sonnet-4-6")

MIN_REQUIREMENTS_LENGTH = 50

# Per-task log callback — set by orchestrator before each task, read by PersonAgent.
# Signature: (level: str, message: str) -> None
task_log: ContextVar = ContextVar("task_log", default=None)
