import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent

COMPANY_DIR = BASE_DIR / "company"
STATE_FILE = COMPANY_DIR / "state.yaml"
TEAMS_DIR = COMPANY_DIR / "teams"
SKILLS_DIR = COMPANY_DIR / "skills"
PROJECTS_DIR = BASE_DIR / "projects"

MODEL = os.environ.get("AICOMPANY_MODEL", "claude-sonnet-4-6")

MAX_TOKENS_CTO = 4096
MAX_TOKENS_HR = 2048
MAX_TOKENS_TEAM = 8096


def require_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill it in, "
            "then run: export ANTHROPIC_API_KEY=<your-key>"
        )
    return key
