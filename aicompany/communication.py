"""
Session management and async pattern dispatch.

Pattern implementations live in patterns.py.
This module owns create_session() and run_pattern(), and re-exports pattern
functions so existing callers don't need to update their imports.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from .models import Person, Session, SessionRules
from .patterns import (
    PATTERNS,
    run_lead_delegates,
    run_pair_review,
)

if TYPE_CHECKING:
    from .models import Skill

__all__ = [
    "create_session",
    "run_pattern",
    "run_lead_delegates",
    "run_pair_review",
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


async def run_pattern(
    pattern_name: str,
    session: Session,
    lead: Person,
    members: list[Person],
    task_title: str,
    task_description: str,
    project_context: str,
    workspace: Path,
    skill_registry: dict[str, Skill] | None = None,
    on_status: callable = None,
) -> str:
    """Dispatch to a named communication pattern. Falls back to lead_delegates."""
    fn = PATTERNS.get(pattern_name, run_lead_delegates)
    return await fn(
        session, lead, members, task_title, task_description,
        project_context, workspace, skill_registry, on_status,
    )
