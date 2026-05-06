"""
Communication pattern implementations for team sessions.

Each pattern drives the message sequence for a particular collaboration style.
run_pattern() in communication.py dispatches to these by name.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from . import config
from .models import Message, Person, Session

if TYPE_CHECKING:
    from .llm_backend import Reasoner
    from .models import Skill


def _members_by_role(members: list[Person], role: str, exclude_id: str = "") -> list[Person]:
    return [m for m in members if m.role == role and m.id != exclude_id]


def _agent_rules(session_rules_text: str, workspace: str) -> str:
    """Combine session communication rules with workspace file-writing instructions."""
    if not workspace:
        return session_rules_text
    return session_rules_text + f"""

## File output
Workspace: `{workspace}`
Write every implementation file using the write_file MCP tool.
Read existing files with read_file. Run tests/commands with run_command."""


def _format_task_for_lead(
    title: str, description: str, context: str, members: list[Person],
) -> str:
    member_list = "\n".join(
        f"- {m.name} (role: {m.role}, id: {m.id})" for m in members
    )
    return f"""\
## Task to plan

**{title}**

{description}

## Project Context

{context}

## Your team members

{member_list}

---

As team lead, produce a brief that:
1. Summarises the overall approach
2. Assigns a specific sub-task to each team member by their name
3. Specifies what each member should produce

Format as Markdown. Be concise and directive.
"""


def run_lead_delegates(
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
    """
    Lead delegates pattern:
      1. Lead receives task → produces a brief
      2. Each non-lead member receives brief → produces their contribution
      3. Lead synthesizes final output
    """
    _status = on_status or (lambda msg: None)
    rules_text = session.rules.describe(lead.id, session.participants)

    session.add_message(Message(
        sender="orchestrator", recipient=lead.id, kind="task",
        content=_format_task_for_lead(task_title, task_description, project_context, members),
    ))
    _status(f"{lead.name} (lead) writing brief...")
    brief = reasoner.think(lead, session.messages_for(lead.id),
                           skill_registry, _agent_rules(rules_text, workspace), max_tokens)
    session.add_message(Message(sender=lead.id, recipient="team", kind="brief", content=brief))
    session.advance_round()

    contributions = []
    for person in [m for m in members if m.id != lead.id]:
        person_rules = session.rules.describe(person.id, session.participants)
        _status(f"{person.name} ({person.role}) executing...")
        output = reasoner.think(person, session.messages_for(person.id),
                                skill_registry, _agent_rules(person_rules, workspace), max_tokens)
        session.add_message(Message(sender=person.id, recipient=lead.id, kind="result", content=output))
        contributions.append({"name": person.name, "output": output})
    session.advance_round()

    if contributions:
        _status(f"{lead.name} (lead) synthesizing...")
        final = reasoner.think(lead, session.messages_for(lead.id),
                               skill_registry, _agent_rules(rules_text, workspace), max_tokens)
    else:
        final = brief

    session.add_message(Message(sender=lead.id, recipient="orchestrator", kind="result", content=final))
    session.complete()
    return final


def run_pair_review(
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
    """
    Pair review pattern:
      1. Lead briefs → 2. Coder produces → 3. Reviewer reviews
      4. Coder revises → 5. Lead synthesizes
    Falls back to lead_delegates if team lacks coder/reviewer.
    """
    _status = on_status or (lambda msg: None)
    rules_text = session.rules.describe(lead.id, session.participants)

    coders = _members_by_role(members, "coder", exclude_id=lead.id)
    reviewers = _members_by_role(members, "reviewer", exclude_id=lead.id)
    coder = coders[0] if coders else None
    reviewer = reviewers[0] if reviewers else None

    if not coder or not reviewer:
        return run_lead_delegates(session, lead, members, task_title,
                                  task_description, project_context,
                                  reasoner, skill_registry, max_tokens, on_status, workspace)

    session.add_message(Message(
        sender="orchestrator", recipient=lead.id, kind="task",
        content=_format_task_for_lead(task_title, task_description, project_context, members),
    ))
    _status(f"{lead.name} (lead) writing brief...")
    brief = reasoner.think(lead, session.messages_for(lead.id),
                           skill_registry, _agent_rules(rules_text, workspace), max_tokens)
    session.add_message(Message(sender=lead.id, recipient="team", kind="brief", content=brief))
    session.advance_round()

    coder_rules = session.rules.describe(coder.id, session.participants)
    _status(f"{coder.name} (coder) implementing...")
    code = reasoner.think(coder, session.messages_for(coder.id),
                          skill_registry, _agent_rules(coder_rules, workspace), max_tokens)
    session.add_message(Message(sender=coder.id, recipient=reviewer.id, kind="result", content=code))
    session.advance_round()

    reviewer_rules = session.rules.describe(reviewer.id, session.participants)
    _status(f"{reviewer.name} (reviewer) reviewing...")
    review = reasoner.think(reviewer, session.messages_for(reviewer.id),
                            skill_registry, _agent_rules(reviewer_rules, workspace), max_tokens)
    session.add_message(Message(sender=reviewer.id, recipient=coder.id, kind="review", content=review))

    if not session.is_complete():
        session.advance_round()
        _status(f"{coder.name} (coder) revising...")
        revised = reasoner.think(coder, session.messages_for(coder.id),
                                 skill_registry, _agent_rules(coder_rules, workspace), max_tokens)
        session.add_message(Message(sender=coder.id, recipient=lead.id, kind="result", content=revised))

    _status(f"{lead.name} (lead) finalizing...")
    final = reasoner.think(lead, session.messages_for(lead.id),
                           skill_registry, _agent_rules(rules_text, workspace), max_tokens)
    session.add_message(Message(sender=lead.id, recipient="orchestrator", kind="result", content=final))
    session.complete()
    return final


def run_develop_test_review(
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
    """
    Develop-test-review pattern:
      1. Lead briefs → 2. Coder implements → 3. Tester writes tests
      4. Reviewer reviews → 5. Coder revises → 6. Lead synthesizes
    Falls back to pair_review (no tester) or lead_delegates (no coder/reviewer).
    """
    _status = on_status or (lambda msg: None)

    coders = _members_by_role(members, "coder", exclude_id=lead.id)
    testers = _members_by_role(members, "tester", exclude_id=lead.id)
    reviewers = _members_by_role(members, "reviewer", exclude_id=lead.id)
    coder = coders[0] if coders else None
    tester = testers[0] if testers else None
    reviewer = reviewers[0] if reviewers else None

    if not tester:
        return run_pair_review(session, lead, members, task_title, task_description,
                               project_context, reasoner, skill_registry, max_tokens,
                               on_status, workspace)
    if not coder or not reviewer:
        return run_lead_delegates(session, lead, members, task_title, task_description,
                                  project_context, reasoner, skill_registry, max_tokens,
                                  on_status, workspace)

    rules_text = session.rules.describe(lead.id, session.participants)

    session.add_message(Message(
        sender="orchestrator", recipient=lead.id, kind="task",
        content=_format_task_for_lead(task_title, task_description, project_context, members),
    ))
    _status(f"{lead.name} (lead) writing brief...")
    brief = reasoner.think(lead, session.messages_for(lead.id),
                           skill_registry, _agent_rules(rules_text, workspace), max_tokens)
    session.add_message(Message(sender=lead.id, recipient="team", kind="brief", content=brief))
    session.advance_round()

    coder_rules = session.rules.describe(coder.id, session.participants)
    _status(f"{coder.name} (coder) implementing...")
    code = reasoner.think(coder, session.messages_for(coder.id),
                          skill_registry, _agent_rules(coder_rules, workspace), max_tokens)
    session.add_message(Message(sender=coder.id, recipient=tester.id, kind="result", content=code))
    session.advance_round()

    tester_rules = session.rules.describe(tester.id, session.participants)
    _status(f"{tester.name} (tester) writing requirement tests...")
    tests = reasoner.think(tester, session.messages_for(tester.id),
                           skill_registry, _agent_rules(tester_rules, workspace), max_tokens)
    session.add_message(Message(sender=tester.id, recipient=reviewer.id, kind="result", content=tests))

    if session.is_complete():
        session.add_message(Message(sender=lead.id, recipient="orchestrator", kind="result", content=brief))
        session.complete()
        return brief

    session.advance_round()
    reviewer_rules = session.rules.describe(reviewer.id, session.participants)
    _status(f"{reviewer.name} (reviewer) reviewing code and requirement tests...")
    review = reasoner.think(reviewer, session.messages_for(reviewer.id),
                            skill_registry, _agent_rules(reviewer_rules, workspace), max_tokens)
    session.add_message(Message(sender=reviewer.id, recipient=coder.id, kind="review", content=review))

    if not session.is_complete():
        session.advance_round()
        _status(f"{coder.name} (coder) revising...")
        revised = reasoner.think(coder, session.messages_for(coder.id),
                                 skill_registry, _agent_rules(coder_rules, workspace), max_tokens)
        session.add_message(Message(sender=coder.id, recipient=lead.id, kind="result", content=revised))

    _status(f"{lead.name} (lead) finalizing with traceability summary...")
    final = reasoner.think(lead, session.messages_for(lead.id),
                           skill_registry, _agent_rules(rules_text, workspace), max_tokens)
    session.add_message(Message(sender=lead.id, recipient="orchestrator", kind="result", content=final))
    session.complete()
    return final


PATTERNS = {
    "lead_delegates": run_lead_delegates,
    "pair_review": run_pair_review,
    "develop_test_review": run_develop_test_review,
}
