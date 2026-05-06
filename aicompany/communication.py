"""
Session management and pattern dispatch.

Pattern implementations live in patterns.py.
This module owns create_session() and run_pattern(), and re-exports pattern
functions so existing callers don't need to update their imports.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from . import config
from .models import Person, Session, SessionRules
from .patterns import (
    PATTERNS,
    _agent_rules,
    run_lead_delegates,
    run_pair_review,
    run_develop_test_review,
)

if TYPE_CHECKING:
    from .llm_backend import Reasoner
    from .models import Skill

# Re-exported for backward compatibility
__all__ = [
    "create_session",
    "run_pattern",
    "_agent_rules",
    "run_lead_delegates",
    "run_pair_review",
    "run_develop_test_review",
]


def create_session(
    task_id: str,
    participants: list[str],
    rules: SessionRules | None = None,
) -> Session:
    return Session(
        id=uuid.uuid4().hex[:12],
        task_id=task_id,
        participants=participants,
        rules=rules or SessionRules(),
    )


def run_pattern(
    pattern_name: str,
    session: Session,
    lead: Person,
    members: list[Person],
    task_title: str,
    task_description: str,
    project_context: str,
    reasoner: Reasoner,
    skill_registry: dict[str, Skill] | None = None,
    max_tokens: int = config.MAX_TOKENS_TEAM,
    on_status: callable = None,
    workspace: str = "",
) -> str:
    """Dispatch to a named communication pattern. Falls back to lead_delegates."""
    fn = PATTERNS.get(pattern_name, run_lead_delegates)
    return fn(session, lead, members, task_title, task_description,
              project_context, reasoner, skill_registry, max_tokens, on_status,
              workspace)
