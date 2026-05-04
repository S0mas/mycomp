import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent

COMPANY_DIR = BASE_DIR / "company"
STATE_FILE = COMPANY_DIR / "state.yaml"
TEAMS_DIR = COMPANY_DIR / "teams"
SKILLS_DIR = COMPANY_DIR / "skills"
PROJECTS_DIR = BASE_DIR / "projects"

MODEL = os.environ.get("AICOMPANY_MODEL", "claude-sonnet-4-6")
LLM_BACKEND = os.environ.get("AICOMPANY_LLM_BACKEND", "anthropic")

MAX_TOKENS_CTO = 4096
MAX_TOKENS_HR = 2048
MAX_TOKENS_TEAM = 8096
MAX_TOKENS_EVAL = 2048

MIN_REQUIREMENTS_LENGTH = 50   # characters — below this, reject as too vague
MIN_SCORE_TO_PROCEED = 3.5    # overall score below this → hard block, cannot proceed
MIN_DIMENSION_SCORE = 3       # any single dimension below this → hard block
MAX_TOKENS_AUTOFIX = 4096     # token budget for requirements autofix
