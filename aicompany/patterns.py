"""
Async communication pattern implementations.

Each pattern creates one PersonAgent per team member. Agents that have
multiple turns (lead in pair_review, coder in develop_test_review) keep
their process alive between turns so context accumulates naturally.
Messages passed to think() carry only the *new* information for that turn.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .models import Message, Person, Session
from .person_agent import PersonAgent

if TYPE_CHECKING:
    from .models import Skill


def _members_by_role(members: list[Person], role: str, exclude_id: str = "") -> list[Person]:
    return [m for m in members if m.role == role and m.id != exclude_id]


def _step(session: Session, sender: str, kind: str, n: int = 1) -> str | None:
    """Return content of the Nth already-saved message from sender with kind, or None."""
    matches = [m.content for m in session.messages if m.sender == sender and m.kind == kind]
    return matches[n - 1] if len(matches) >= n else None


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


async def run_lead_delegates(
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
    """
    Lead delegates pattern:
      1. Lead receives task → produces a brief
      2. Each non-lead member receives brief → produces their contribution
      3. Lead synthesizes final output

    The lead's agent stays alive for steps 1 and 3 so it retains full context.
    """
    _status = on_status or (lambda msg: None)

    async with PersonAgent(lead, workspace, skill_registry) as lead_agent:
        # Step 1: lead brief
        brief = _step(session, lead.id, "brief")
        if brief:
            _status(f"{lead.name} (lead) brief already done — resuming")
        else:
            task_msg = _format_task_for_lead(task_title, task_description, project_context, members)
            session.add_message(Message(
                sender="orchestrator", recipient=lead.id, kind="task", content=task_msg,
            ))
            _status(f"{lead.name} (lead) writing brief...")
            brief = await lead_agent.think(task_msg)
            session.add_message(Message(sender=lead.id, recipient="team", kind="brief", content=brief))
            session.advance_round()

        # Step 2: each non-lead member executes
        contributions: list[str] = []
        for person in [m for m in members if m.id != lead.id]:
            existing = _step(session, person.id, "result")
            if existing:
                _status(f"{person.name} ({person.role}) already done — resuming")
                contributions.append(existing)
                continue
            _status(f"{person.name} ({person.role}) executing...")
            async with PersonAgent(person, workspace, skill_registry) as agent:
                output = await agent.think(f"**Brief from {lead.name}:**\n\n{brief}")
                session.add_message(Message(
                    sender=person.id, recipient=lead.id, kind="result", content=output,
                ))
                contributions.append(output)

        # Step 3: lead synthesizes
        final = _step(session, lead.id, "result")
        if final:
            _status(f"{lead.name} (lead) synthesis already done — resuming")
        elif contributions:
            _status(f"{lead.name} (lead) synthesizing...")
            contrib_text = "\n\n---\n\n".join(contributions)
            # Include brief for context (safe when resuming with a fresh lead process)
            final = await lead_agent.think(
                f"**Your earlier brief:**\n{brief}\n\n"
                f"**Team contributions:**\n{contrib_text}\n\n"
                f"Synthesize into a final output."
            )
        else:
            final = brief

        if not session.is_complete():
            session.add_message(Message(
                sender=lead.id, recipient="orchestrator", kind="result", content=final,
            ))
            session.complete()

    return final


async def run_pair_review(
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
    """
    Pair review pattern:
      1. Lead briefs → 2. Coder implements → 3. Reviewer reviews
      4. Coder revises → 5. Lead synthesizes

    Lead and Coder keep their processes alive for their multi-turn work.
    Falls back to lead_delegates if team lacks a reviewer.
    For teams with reviewer but no coder (e.g. CTO team), lead acts as producer.
    """
    _status = on_status or (lambda msg: None)

    coders = _members_by_role(members, "coder", exclude_id=lead.id)
    reviewers = _members_by_role(members, "reviewer", exclude_id=lead.id)
    coder = coders[0] if coders else None
    reviewer = reviewers[0] if reviewers else None

    if not reviewer:
        return await run_lead_delegates(
            session, lead, members, task_title, task_description,
            project_context, workspace, skill_registry, on_status,
        )

    if not coder:
        # Lead acts as producer: lead drafts → reviewer reviews → lead revises → lead finalizes.
        async with PersonAgent(lead, workspace, skill_registry) as lead_agent:
            # Step 1: lead initial draft
            draft = _step(session, lead.id, "result")
            if draft:
                _status(f"{lead.name} (lead) draft already done — resuming")
            else:
                task_msg = _format_task_for_lead(task_title, task_description, project_context, members)
                session.add_message(Message(
                    sender="orchestrator", recipient=lead.id, kind="task", content=task_msg,
                ))
                _status(f"{lead.name} (lead) producing initial draft...")
                draft = await lead_agent.think(task_msg)
                session.add_message(Message(
                    sender=lead.id, recipient=reviewer.id, kind="result", content=draft,
                ))
                session.advance_round()

            # Step 2: reviewer reviews
            review = _step(session, reviewer.id, "review")
            if review:
                _status(f"{reviewer.name} (reviewer) review already done — resuming")
            else:
                _status(f"{reviewer.name} (reviewer) reviewing...")
                async with PersonAgent(reviewer, workspace, skill_registry) as reviewer_agent:
                    review = await reviewer_agent.think(
                        f"**Draft from {lead.name}:**\n\n{draft}\n\nPlease review."
                    )
                session.add_message(Message(
                    sender=reviewer.id, recipient=lead.id, kind="review", content=review,
                ))

            # Step 3: lead revision / final
            final = _step(session, lead.id, "result", n=2)
            if final:
                _status(f"{lead.name} (lead) revision already done — resuming")
            elif not session.is_complete():
                session.advance_round()
                _status(f"{lead.name} (lead) revising based on review...")
                final = await lead_agent.think(
                    f"**Your earlier draft:**\n{draft}\n\n"
                    f"**Reviewer feedback:**\n{review}\n\nPlease revise."
                )
            else:
                final = draft

            if not session.is_complete():
                session.add_message(Message(
                    sender=lead.id, recipient="orchestrator", kind="result", content=final,
                ))
                session.complete()

        return final

    # ── Full pair_review: lead + coder + reviewer ─────────────────────────────
    async with PersonAgent(lead, workspace, skill_registry) as lead_agent:
        # Step 1: lead brief
        brief = _step(session, lead.id, "brief")
        if brief:
            _status(f"{lead.name} (lead) brief already done — resuming")
        else:
            task_msg = _format_task_for_lead(task_title, task_description, project_context, members)
            session.add_message(Message(
                sender="orchestrator", recipient=lead.id, kind="task", content=task_msg,
            ))
            _status(f"{lead.name} (lead) writing brief...")
            brief = await lead_agent.think(task_msg)
            session.add_message(Message(sender=lead.id, recipient="team", kind="brief", content=brief))
            session.advance_round()

        async with PersonAgent(coder, workspace, skill_registry) as coder_agent:
            # Step 2: coder implements
            code = _step(session, coder.id, "result")
            if code:
                _status(f"{coder.name} (coder) implementation already done — resuming")
            else:
                _status(f"{coder.name} (coder) implementing...")
                code = await coder_agent.think(f"**Brief from {lead.name}:**\n\n{brief}")
                session.add_message(Message(
                    sender=coder.id, recipient=reviewer.id, kind="result", content=code,
                ))
                session.advance_round()

            # Step 3: reviewer reviews
            review = _step(session, reviewer.id, "review")
            if review:
                _status(f"{reviewer.name} (reviewer) review already done — resuming")
            else:
                _status(f"{reviewer.name} (reviewer) reviewing...")
                async with PersonAgent(reviewer, workspace, skill_registry) as reviewer_agent:
                    review = await reviewer_agent.think(
                        f"**Brief:**\n{brief}\n\n**Implementation:**\n{code}\n\nPlease review."
                    )
                session.add_message(Message(
                    sender=reviewer.id, recipient=coder.id, kind="review", content=review,
                ))

            # Step 4: coder revises
            revised = _step(session, coder.id, "result", n=2)
            if revised:
                _status(f"{coder.name} (coder) revision already done — resuming")
            elif not session.is_complete():
                session.advance_round()
                _status(f"{coder.name} (coder) revising...")
                # Include prior code for context (safe when resuming with fresh coder process)
                revised = await coder_agent.think(
                    f"**Your implementation:**\n{code}\n\n"
                    f"**Review feedback:**\n{review}\n\nPlease revise."
                )
                session.add_message(Message(
                    sender=coder.id, recipient=lead.id, kind="result", content=revised,
                ))
            else:
                revised = code

        # Step 5: lead finalizes
        final = _step(session, lead.id, "result")
        if final:
            _status(f"{lead.name} (lead) final already done — resuming")
        else:
            _status(f"{lead.name} (lead) finalizing...")
            final = await lead_agent.think(
                f"**Your earlier brief:**\n{brief}\n\n"
                f"**Final implementation:**\n{revised}\n\n"
                f"**Review:**\n{review}\n\nProvide the final synthesis."
            )
            session.add_message(Message(
                sender=lead.id, recipient="orchestrator", kind="result", content=final,
            ))

        if not session.is_complete():
            session.complete()

    return final


async def run_develop_test_review(
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
    """
    Develop-test-review pattern:
      1. Lead briefs → 2. Coder implements → 3. Tester writes tests
      4. Reviewer reviews → 5. Coder revises → 6. Lead synthesizes

    Lead and Coder keep processes alive for their multi-turn work.
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
        return await run_pair_review(
            session, lead, members, task_title, task_description,
            project_context, workspace, skill_registry, on_status,
        )
    if not coder or not reviewer:
        return await run_lead_delegates(
            session, lead, members, task_title, task_description,
            project_context, workspace, skill_registry, on_status,
        )

    async with PersonAgent(lead, workspace, skill_registry) as lead_agent:
        # Step 1: lead brief
        brief = _step(session, lead.id, "brief")
        if brief:
            _status(f"{lead.name} (lead) brief already done — resuming")
        else:
            task_msg = _format_task_for_lead(task_title, task_description, project_context, members)
            session.add_message(Message(
                sender="orchestrator", recipient=lead.id, kind="task", content=task_msg,
            ))
            _status(f"{lead.name} (lead) writing brief...")
            brief = await lead_agent.think(task_msg)
            session.add_message(Message(sender=lead.id, recipient="team", kind="brief", content=brief))
            session.advance_round()

        async with PersonAgent(coder, workspace, skill_registry) as coder_agent:
            # Step 2: coder implements
            code = _step(session, coder.id, "result")
            if code:
                _status(f"{coder.name} (coder) implementation already done — resuming")
            else:
                _status(f"{coder.name} (coder) implementing...")
                code = await coder_agent.think(f"**Brief from {lead.name}:**\n\n{brief}")
                session.add_message(Message(
                    sender=coder.id, recipient=tester.id, kind="result", content=code,
                ))
                session.advance_round()

            # Step 3: tester writes tests
            tests = _step(session, tester.id, "result")
            if tests:
                _status(f"{tester.name} (tester) tests already done — resuming")
            elif not session.is_complete():
                _status(f"{tester.name} (tester) writing tests...")
                async with PersonAgent(tester, workspace, skill_registry) as tester_agent:
                    tests = await tester_agent.think(
                        f"**Brief:**\n{brief}\n\n**Implementation:**\n{code}\n\n"
                        f"Write requirement tests."
                    )
                session.add_message(Message(
                    sender=tester.id, recipient=reviewer.id, kind="result", content=tests,
                ))

            if session.is_complete():
                return _step(session, lead.id, "result") or brief

            # Step 4: reviewer reviews
            review = _step(session, reviewer.id, "review")
            if review:
                _status(f"{reviewer.name} (reviewer) review already done — resuming")
            else:
                session.advance_round()
                _status(f"{reviewer.name} (reviewer) reviewing...")
                async with PersonAgent(reviewer, workspace, skill_registry) as reviewer_agent:
                    review = await reviewer_agent.think(
                        f"**Brief:**\n{brief}\n\n**Implementation:**\n{code}\n\n"
                        f"**Tests:**\n{tests}\n\nReview the implementation and tests."
                    )
                session.add_message(Message(
                    sender=reviewer.id, recipient=coder.id, kind="review", content=review,
                ))

            # Step 5: coder revises
            revised = _step(session, coder.id, "result", n=2)
            if revised:
                _status(f"{coder.name} (coder) revision already done — resuming")
            elif not session.is_complete():
                session.advance_round()
                _status(f"{coder.name} (coder) revising...")
                revised = await coder_agent.think(
                    f"**Your implementation:**\n{code}\n\n"
                    f"**Review feedback:**\n{review}\n\nPlease revise."
                )
                session.add_message(Message(
                    sender=coder.id, recipient=lead.id, kind="result", content=revised,
                ))
            else:
                revised = code

        # Step 6: lead synthesizes
        final = _step(session, lead.id, "result")
        if final:
            _status(f"{lead.name} (lead) final already done — resuming")
        else:
            _status(f"{lead.name} (lead) finalizing with traceability summary...")
            final = await lead_agent.think(
                f"**Your earlier brief:**\n{brief}\n\n"
                f"**Final implementation:**\n{revised}\n\n"
                f"**Tests:**\n{tests}\n\n"
                f"**Review:**\n{review}\n\nProvide the final synthesis with traceability."
            )
            session.add_message(Message(
                sender=lead.id, recipient="orchestrator", kind="result", content=final,
            ))

        if not session.is_complete():
            session.complete()

    return final


PATTERNS = {
    "lead_delegates": run_lead_delegates,
    "pair_review": run_pair_review,
    "develop_test_review": run_develop_test_review,
}
