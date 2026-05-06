from __future__ import annotations

from dataclasses import dataclass, field, asdict

from ._utils import _now, _msg_id


@dataclass
class Message:
    """A single communication between persons, or from the system."""
    sender: str
    recipient: str
    kind: str
    content: str
    context: dict = field(default_factory=dict)
    id: str = field(default_factory=_msg_id)
    timestamp: str = field(default_factory=_now)

    @classmethod
    def from_dict(cls, d: dict) -> Message:
        return cls(
            sender=d["sender"],
            recipient=d["recipient"],
            kind=d.get("kind", "task"),
            content=d.get("content", ""),
            context=d.get("context", {}),
            id=d.get("id", _msg_id()),
            timestamp=d.get("timestamp", _now()),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def system(cls, recipient: str, content: str, **ctx) -> Message:
        return cls(sender="system", recipient=recipient, kind="system",
                   content=content, context=ctx)


@dataclass
class SessionRules:
    """Communication rules for a session."""
    pattern: str = "lead_delegates"
    max_rounds: int = 3
    allow_direct: bool = True
    channels: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> SessionRules:
        return cls(
            pattern=d.get("pattern", "lead_delegates"),
            max_rounds=d.get("max_rounds", 3),
            allow_direct=d.get("allow_direct", True),
            channels=d.get("channels", []),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    def describe(self, participant_id: str, all_participants: list[str]) -> str:
        others = [p for p in all_participants if p != participant_id]
        lines = [
            "Communication rules for this session:",
            f"- Pattern: {self.pattern}",
            f"- Max rounds: {self.max_rounds}",
            f"- Other participants: {', '.join(others)}",
        ]
        if self.allow_direct:
            if self.channels:
                my_peers = [
                    b if a == participant_id else a
                    for a, b in self.channels
                    if participant_id in (a, b)
                ]
                lines.append(
                    f"- You may message directly: {', '.join(my_peers)}"
                    if my_peers else "- You may not send direct messages to others"
                )
            else:
                lines.append("- You may message any participant directly")
        else:
            lines.append("- Direct messages are not allowed — communicate through the lead")
        return "\n".join(lines)


@dataclass
class Session:
    """Runtime container for a multi-person conversation on a task."""
    id: str
    task_id: str
    participants: list[str]
    rules: SessionRules = field(default_factory=SessionRules)
    messages: list[Message] = field(default_factory=list)
    round: int = 0
    status: str = "active"

    def can_send(self, sender: str, recipient: str) -> tuple[bool, str]:
        if self.status != "active":
            return False, f"Session is {self.status}"
        if self.round >= self.rules.max_rounds:
            return False, f"Max rounds ({self.rules.max_rounds}) reached"
        if sender not in self.participants and sender != "system":
            return False, f"{sender} is not a participant in this session"
        if recipient not in self.participants and recipient not in ("team", "orchestrator", "system"):
            return False, f"{recipient} is not a participant in this session"
        if self.rules.channels and sender != "system":
            pair_allowed = (
                [sender, recipient] in self.rules.channels or
                [recipient, sender] in self.rules.channels
            )
            if not pair_allowed and self.rules.allow_direct:
                return False, f"No direct channel between {sender} and {recipient}"
        return True, ""

    def add_message(self, msg: Message) -> Message | None:
        allowed, reason = self.can_send(msg.sender, msg.recipient)
        if not allowed:
            self.messages.append(msg)
            feedback = Message.system(
                msg.sender,
                f"Message to {msg.recipient} was not delivered: {reason}. "
                f"Please include your final output now.",
                reason=reason, blocked_message_id=msg.id,
            )
            self.messages.append(feedback)
            return feedback
        self.messages.append(msg)
        return None

    def advance_round(self) -> None:
        self.round += 1

    def complete(self) -> None:
        self.status = "complete"

    def is_complete(self) -> bool:
        return self.status != "active" or self.round >= self.rules.max_rounds

    def messages_for(self, person_id: str) -> list[Message]:
        return [m for m in self.messages
                if m.recipient in (person_id, "team") or m.sender == person_id]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "participants": self.participants,
            "rules": self.rules.to_dict(),
            "messages": [m.to_dict() for m in self.messages],
            "round": self.round,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Session:
        return cls(
            id=d["id"],
            task_id=d["task_id"],
            participants=d.get("participants", []),
            rules=SessionRules.from_dict(d.get("rules", {})),
            messages=[Message.from_dict(m) for m in d.get("messages", [])],
            round=d.get("round", 0),
            status=d.get("status", "active"),
        )
