"""PersonAgent: a persistent Claude Code process backing one person in a task.

Each agent wraps a ClaudeSDKClient that stays alive for the duration of the task,
so the person accumulates context across their turns (brief → synthesis, implement → revise).
Messages are sent incrementally; each agent only receives the new information for their turn.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from . import config
from .models import build_prompt

if TYPE_CHECKING:
    from .models import Person, Skill


class PersonAgent:
    """A persistent Claude Code agent representing one person for the duration of a task."""

    def __init__(
        self,
        person: Person,
        workspace: Path,
        skill_registry: dict[str, Skill] | None = None,
    ) -> None:
        from claude_code_sdk import ClaudeSDKClient, ClaudeCodeOptions

        system = build_prompt(person, skill_registry or {})
        self._options = ClaudeCodeOptions(
            system_prompt=system,
            cwd=str(workspace),
            permission_mode="bypassPermissions",
            max_turns=50,
        )
        self._client = ClaudeSDKClient(self._options)
        self.person = person
        self._log = config.task_log.get()

    async def __aenter__(self) -> PersonAgent:
        await self._client.connect()
        return self

    async def __aexit__(self, *args: object) -> bool:
        await self._client.disconnect()
        return False

    async def think(self, message: str) -> str:
        """Send a message and collect Claude's full response."""
        from claude_code_sdk import AssistantMessage, ResultMessage, TextBlock

        await self._client.query(message)
        parts: list[str] = []
        async for msg in self._client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock) and block.text:
                        parts.append(block.text)
            elif isinstance(msg, ResultMessage):
                if msg.is_error:
                    raise RuntimeError(
                        f"{self.person.name}: agent error — {msg.result or 'unknown'}"
                    )
                if self._log:
                    extras = f" turns={msg.num_turns}"
                    if msg.total_cost_usd is not None:
                        extras += f" cost=${msg.total_cost_usd:.4f}"
                    self._log("AGENT", f"{self.person.name} turn done{extras}")
                break
        return "\n".join(filter(None, parts))
