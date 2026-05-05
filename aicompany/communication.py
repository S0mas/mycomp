"""
Communication patterns for team sessions.

Each pattern defines the message flow for how a team collaborates on a task.
The orchestrator creates a Session with rules, then the pattern drives the
sequence of think() calls and message routing.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from . import config
from .models import Message, Person, Session, SessionRules

if TYPE_CHECKING:
    from .llm_backend import Reasoner
    from .models import Skill


def create_session(
    task_id: str,
    participants: list[str],
    rules: SessionRules | None = None,
) -> Session:
    """Create a new Session for a task."""
    return Session(
        id=uuid.uuid4().hex[:12],
        task_id=task_id,
        participants=participants,
        rules=rules or SessionRules(),
    )


# ── Pattern: lead_delegates ───────────────────────────────────────────────────

def _agent_rules(session_rules_text: str, workspace: str) -> str:
    """Combine session communication rules with workspace file-writing instructions."""
    if not workspace:
        return session_rules_text
    return session_rules_text + f"""

## File output
Workspace: `{workspace}`
Write every implementation file using the write_file MCP tool.
Read existing files with read_file. Run tests/commands with run_command."""


def run_lead_delegates(
    session: Session,
    lead: Person,
    members: list[Person],
    task_title: str,
    task_description: str,
    project_context: str,
    reasoner: Reasoner,
    skill_registry: "dict[str, Skill] | None" = None,
    max_tokens: int = config.MAX_TOKENS_TEAM,
    on_status: callable = None,
    workspace: str = "",
) -> str:
    """
    Lead delegates pattern:
      1. Lead receives task → produces a brief
      2. Each non-lead member receives brief → produces their contribution
      3. Lead receives all contributions → synthesizes final output

    Returns the final synthesized output.
    """
    _status = on_status or (lambda msg: None)
    rules_text = session.rules.describe(lead.id, session.participants)

    # Build person lookup
    all_persons = {lead.id: lead}
    for m in members:
        all_persons[m.id] = m

    # ── Round 1: Lead gets the task and writes a brief ────────────────────
    task_msg = Message(
        sender="orchestrator",
        recipient=lead.id,
        kind="task",
        content=_format_task_for_lead(task_title, task_description,
                                      project_context, members),
    )
    session.add_message(task_msg)

    _status(f"{lead.name} (lead) writing brief...")
    lead_messages = session.messages_for(lead.id)
    brief = reasoner.think(lead, lead_messages, skill_registry,
                           _agent_rules(rules_text, workspace), max_tokens)

    brief_msg = Message(sender=lead.id, recipient="team", kind="brief",
                        content=brief)
    session.add_message(brief_msg)
    session.advance_round()

    # ── Round 2: Each non-lead member executes their part ─────────────────
    contributions = []
    for person in members:
        if person.id == lead.id:
            continue

        person_rules_text = session.rules.describe(person.id, session.participants)
        _status(f"{person.name} ({person.role}) executing...")

        person_messages = session.messages_for(person.id)
        output = reasoner.think(person, person_messages, skill_registry,
                                _agent_rules(person_rules_text, workspace), max_tokens)

        result_msg = Message(sender=person.id, recipient=lead.id,
                             kind="result", content=output)
        feedback = session.add_message(result_msg)

        if feedback is None:
            contributions.append({"name": person.name, "output": output})
        else:
            # Message was blocked — person got feedback, use what we have
            contributions.append({"name": person.name, "output": output})

    session.advance_round()

    # ── Round 3: Lead synthesizes ─────────────────────────────────────────
    if contributions:
        _status(f"{lead.name} (lead) synthesizing...")

        synth_msgs = session.messages_for(lead.id)
        final = reasoner.think(lead, synth_msgs, skill_registry,
                               _agent_rules(rules_text, workspace), max_tokens)
    else:
        # Single-person team
        final = brief

    final_msg = Message(sender=lead.id, recipient="orchestrator",
                        kind="result", content=final)
    session.add_message(final_msg)
    session.complete()

    return final


# ── Pattern: pair_review ──────────────────────────────────────────────────────

def run_pair_review(
    session: Session,
    lead: Person,
    members: list[Person],
    task_title: str,
    task_description: str,
    project_context: str,
    reasoner: Reasoner,
    skill_registry: "dict[str, Skill] | None" = None,
    max_tokens: int = config.MAX_TOKENS_TEAM,
    on_status: callable = None,
    workspace: str = "",
) -> str:
    """
    Pair review pattern:
      1. Lead briefs the team
      2. Coder produces output
      3. Reviewer reviews and suggests changes
      4. Coder revises based on review
      5. Lead approves/synthesizes final output

    Returns the final output.
    """
    _status = on_status or (lambda msg: None)
    rules_text = session.rules.describe(lead.id, session.participants)

    coders = [m for m in members if m.role == "coder" and m.id != lead.id]
    reviewers = [m for m in members if m.role == "reviewer" and m.id != lead.id]
    coder = coders[0] if coders else None
    reviewer = reviewers[0] if reviewers else None

    # Fallback to lead_delegates if team lacks coder/reviewer
    if not coder or not reviewer:
        return run_lead_delegates(session, lead, members, task_title,
                                  task_description, project_context,
                                  reasoner, skill_registry, max_tokens, on_status,
                                  workspace)

    # ── Brief ─────────────────────────────────────────────────────────────
    task_msg = Message(sender="orchestrator", recipient=lead.id, kind="task",
                       content=_format_task_for_lead(task_title, task_description,
                                                     project_context, members))
    session.add_message(task_msg)

    _status(f"{lead.name} (lead) writing brief...")
    brief = reasoner.think(lead, session.messages_for(lead.id),
                           skill_registry, _agent_rules(rules_text, workspace), max_tokens)
    session.add_message(Message(sender=lead.id, recipient="team",
                                kind="brief", content=brief))
    session.advance_round()

    # ── Coder produces ────────────────────────────────────────────────────
    coder_rules = session.rules.describe(coder.id, session.participants)
    _status(f"{coder.name} (coder) implementing...")
    code = reasoner.think(coder, session.messages_for(coder.id),
                          skill_registry, _agent_rules(coder_rules, workspace), max_tokens)
    session.add_message(Message(sender=coder.id, recipient=reviewer.id,
                                kind="result", content=code))
    session.advance_round()

    # ── Reviewer reviews ──────────────────────────────────────────────────
    reviewer_rules = session.rules.describe(reviewer.id, session.participants)
    _status(f"{reviewer.name} (reviewer) reviewing...")
    review = reasoner.think(reviewer, session.messages_for(reviewer.id),
                            skill_registry, _agent_rules(reviewer_rules, workspace), max_tokens)
    session.add_message(Message(sender=reviewer.id, recipient=coder.id,
                                kind="review", content=review))

    if not session.is_complete():
        session.advance_round()

        # ── Coder revises ─────────────────────────────────────────────────
        _status(f"{coder.name} (coder) revising...")
        revised = reasoner.think(coder, session.messages_for(coder.id),
                                 skill_registry, _agent_rules(coder_rules, workspace), max_tokens)
        session.add_message(Message(sender=coder.id, recipient=lead.id,
                                    kind="result", content=revised))
    else:
        revised = code

    # ── Lead synthesizes ──────────────────────────────────────────────────
    _status(f"{lead.name} (lead) finalizing...")
    final = reasoner.think(lead, session.messages_for(lead.id),
                           skill_registry, _agent_rules(rules_text, workspace), max_tokens)
    session.add_message(Message(sender=lead.id, recipient="orchestrator",
                                kind="result", content=final))
    session.complete()

    return final


# ── Pattern: develop_test_review ─────────────────────────────────────────────

def run_develop_test_review(
    session: Session,
    lead: Person,
    members: list[Person],
    task_title: str,
    task_description: str,
    project_context: str,
    reasoner: "Reasoner",
    skill_registry: "dict[str, Skill] | None" = None,
    max_tokens: int = config.MAX_TOKENS_TEAM,
    on_status: callable = None,
    workspace: str = "",
) -> str:
    """
    Develop-test-review pattern:
      1. Lead briefs team (with task, project context, and requirement acceptance criteria)
      2. Coder implements code via MCP tools
      3. Tester writes requirement tests to tests/requirements/ via MCP
      4. Reviewer reviews code + requirement tests together
      5. Coder revises (if requested)
      6. Lead synthesizes final output with traceability summary

    Falls back to pair_review if no tester, or lead_delegates if no coder/reviewer/tester.
    """
    _status = on_status or (lambda msg: None)

    coders = [m for m in members if m.role == "coder" and m.id != lead.id]
    testers = [m for m in members if m.role == "tester" and m.id != lead.id]
    reviewers = [m for m in members if m.role == "reviewer" and m.id != lead.id]

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

    # ── Round 1: Lead briefs ──────────────────────────────────────────────────
    task_msg = Message(
        sender="orchestrator", recipient=lead.id, kind="task",
        content=_format_task_for_lead(task_title, task_description, project_context, members),
    )
    session.add_message(task_msg)
    _status(f"{lead.name} (lead) writing brief...")
    brief = reasoner.think(lead, session.messages_for(lead.id),
                           skill_registry, _agent_rules(rules_text, workspace), max_tokens)
    session.add_message(Message(sender=lead.id, recipient="team", kind="brief", content=brief))
    session.advance_round()

    # ── Round 2: Coder implements ─────────────────────────────────────────────
    coder_rules = session.rules.describe(coder.id, session.participants)
    _status(f"{coder.name} (coder) implementing...")
    code = reasoner.think(coder, session.messages_for(coder.id),
                          skill_registry, _agent_rules(coder_rules, workspace), max_tokens)
    session.add_message(Message(sender=coder.id, recipient=tester.id, kind="result", content=code))
    session.advance_round()

    # ── Round 3: Tester writes requirement tests ──────────────────────────────
    tester_rules = session.rules.describe(tester.id, session.participants)
    _status(f"{tester.name} (tester) writing requirement tests...")
    tests = reasoner.think(tester, session.messages_for(tester.id),
                           skill_registry, _agent_rules(tester_rules, workspace), max_tokens)
    session.add_message(Message(sender=tester.id, recipient=reviewer.id, kind="result", content=tests))

    if session.is_complete():
        final = brief
        session.add_message(Message(sender=lead.id, recipient="orchestrator", kind="result", content=final))
        session.complete()
        return final

    session.advance_round()

    # ── Round 4: Reviewer reviews code + tests ────────────────────────────────
    reviewer_rules = session.rules.describe(reviewer.id, session.participants)
    _status(f"{reviewer.name} (reviewer) reviewing code and requirement tests...")
    review = reasoner.think(reviewer, session.messages_for(reviewer.id),
                            skill_registry, _agent_rules(reviewer_rules, workspace), max_tokens)
    session.add_message(Message(sender=reviewer.id, recipient=coder.id, kind="review", content=review))

    if not session.is_complete():
        session.advance_round()

        # ── Round 5: Coder revises ────────────────────────────────────────────
        _status(f"{coder.name} (coder) revising...")
        revised = reasoner.think(coder, session.messages_for(coder.id),
                                 skill_registry, _agent_rules(coder_rules, workspace), max_tokens)
        session.add_message(Message(sender=coder.id, recipient=lead.id, kind="result", content=revised))

    # ── Round 6: Lead synthesizes ─────────────────────────────────────────────
    _status(f"{lead.name} (lead) finalizing with traceability summary...")
    final = reasoner.think(lead, session.messages_for(lead.id),
                           skill_registry, _agent_rules(rules_text, workspace), max_tokens)
    session.add_message(Message(sender=lead.id, recipient="orchestrator", kind="result", content=final))
    session.complete()
    return final


# ── Pattern registry ──────────────────────────────────────────────────────────

PATTERNS = {
    "lead_delegates": run_lead_delegates,
    "pair_review": run_pair_review,
    "develop_test_review": run_develop_test_review,
}


def run_pattern(
    pattern_name: str,
    session: Session,
    lead: Person,
    members: list[Person],
    task_title: str,
    task_description: str,
    project_context: str,
    reasoner: Reasoner,
    skill_registry: "dict[str, Skill] | None" = None,
    max_tokens: int = config.MAX_TOKENS_TEAM,
    on_status: callable = None,
    workspace: str = "",
) -> str:
    """Run a named communication pattern. Falls back to lead_delegates."""
    fn = PATTERNS.get(pattern_name, run_lead_delegates)
    return fn(session, lead, members, task_title, task_description,
              project_context, reasoner, skill_registry, max_tokens, on_status,
              workspace)


# ── Helpers ───────────────────────────────────────────────────────────────────

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
