from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional
import uuid


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _msg_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Skill:
    """Shared knowledge unit — reusable across persons."""
    id: str
    name: str
    category: str = ""          # "language" | "framework" | "tool" | "practice" | ""
    knowledge: list = field(default_factory=list)   # things an agent with this skill should know
    created_at: str = field(default_factory=_now)

    @classmethod
    def from_dict(cls, d: dict) -> "Skill":
        return cls(
            id=d["id"],
            name=d["name"],
            category=d.get("category", ""),
            knowledge=d.get("knowledge", []),
            created_at=d.get("created_at", _now()),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Person:
    id: str
    name: str
    role: str               # "lead" | "coder" | "reviewer" | "architect" | "specialist"
    identity: str           # short, stable — "You are a senior Backend Engineer."
    skills: list = field(default_factory=list)       # skill IDs — references into the skill registry
    knowledge: list = field(default_factory=list)     # person-specific knowledge (learned over time)
    rules: list = field(default_factory=list)          # behavioural rules — how they work and communicate
    tools: list = field(default_factory=list)
    created_at: str = field(default_factory=_now)

    @classmethod
    def from_dict(cls, d: dict) -> "Person":
        return cls(
            id=d["id"],
            name=d["name"],
            role=d.get("role", "specialist"),
            identity=d.get("identity", ""),
            skills=d.get("skills", []),
            knowledge=d.get("knowledge", []),
            rules=d.get("rules", []),
            tools=d.get("tools", []),
            created_at=d.get("created_at", _now()),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Team:
    id: str
    name: str
    skills: list        # union of member skills — used for task assignment matching
    members: list       # list of Person IDs
    lead_id: str        # Person ID of the team lead
    communication: dict = field(default_factory=dict)  # SessionRules config
    created_at: str = field(default_factory=_now)

    @classmethod
    def from_dict(cls, d: dict) -> "Team":
        return cls(
            id=d["id"],
            name=d["name"],
            skills=d.get("skills", []),
            members=d.get("members", []),
            lead_id=d.get("lead_id", ""),
            communication=d.get("communication", {}),
            created_at=d.get("created_at", _now()),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def skill_set(self) -> set:
        return {s.lower() for s in self.skills}


def build_prompt(person: Person, skill_registry: dict | None = None) -> str:
    """Compose a system prompt from a person's structured context and their skills."""
    sections = [person.identity] if person.identity else []

    # Collect knowledge from referenced skills
    skill_knowledge = []
    if skill_registry:
        for skill_id in person.skills:
            skill = skill_registry.get(skill_id)
            if skill and skill.knowledge:
                skill_knowledge.extend(skill.knowledge)

    if skill_knowledge:
        lines = "\n".join(f"- {k}" for k in skill_knowledge)
        sections.append(f"Technical knowledge:\n{lines}")

    # Person-specific knowledge
    if person.knowledge:
        lines = "\n".join(f"- {k}" for k in person.knowledge)
        sections.append(f"Your experience:\n{lines}")

    # Behavioural rules
    if person.rules:
        lines = "\n".join(f"- {r}" for r in person.rules)
        sections.append(f"Rules you follow:\n{lines}")

    return "\n\n".join(sections)


@dataclass
class CompanyState:
    version: str = "1"
    created_at: str = field(default_factory=_now)
    teams: list = field(default_factory=list)
    persons: list = field(default_factory=list)
    skills: list = field(default_factory=list)
    technologies_seen: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "CompanyState":
        return cls(
            version=d.get("version", "1"),
            created_at=d.get("created_at", _now()),
            teams=d.get("teams", []),
            persons=d.get("persons", []),
            skills=d.get("skills", []),
            technologies_seen=d.get("technologies_seen", []),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    def team_ids(self) -> list:
        return [t["id"] for t in self.teams]

    def person_ids(self) -> list:
        return [p["id"] for p in self.persons]

    def skill_ids(self) -> list:
        return [s["id"] for s in self.skills]

    def all_skills(self) -> set:
        skills = set()
        for t in self.teams:
            skills.update(s.lower() for s in t.get("skills", []))
        return skills


@dataclass
class Task:
    id: str
    title: str
    description: str
    assigned_team: str
    depends_on: list = field(default_factory=list)
    status: str = "pending"
    is_checkpoint: bool = False
    output_file: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        return cls(
            id=d["id"],
            title=d["title"],
            description=d["description"],
            assigned_team=d["assigned_team"],
            depends_on=d.get("depends_on", []),
            status=d.get("status", "pending"),
            is_checkpoint=d.get("is_checkpoint", False),
            output_file=d.get("output_file", ""),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ProjectPlan:
    project_id: str
    title: str
    created_at: str = field(default_factory=_now)
    status: str = "pending"
    tech_stack: list = field(default_factory=list)
    teams_required: list = field(default_factory=list)
    tasks: list = field(default_factory=list)
    decisions_log: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "ProjectPlan":
        return cls(
            project_id=d["project_id"],
            title=d["title"],
            created_at=d.get("created_at", _now()),
            status=d.get("status", "pending"),
            tech_stack=d.get("tech_stack", []),
            teams_required=d.get("teams_required", []),
            tasks=[Task.from_dict(t) for t in d.get("tasks", [])],
            decisions_log=d.get("decisions_log", []),
        )

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "title": self.title,
            "created_at": self.created_at,
            "status": self.status,
            "tech_stack": self.tech_stack,
            "teams_required": self.teams_required,
            "tasks": [t.to_dict() for t in self.tasks],
            "decisions_log": self.decisions_log,
        }

    def task_by_id(self, task_id: str) -> Optional[Task]:
        for t in self.tasks:
            if t.id == task_id:
                return t
        return None


@dataclass
class RequirementsEvaluation:
    """Structured assessment of a requirements document before planning."""
    clarity: int            # 1-5: how clear and unambiguous
    completeness: int       # 1-5: how complete (covers scope, constraints, acceptance criteria)
    feasibility: int        # 1-5: how realistic given current company capabilities
    risks: list = field(default_factory=list)         # list of risk strings
    suggestions: list = field(default_factory=list)    # list of improvement suggestions
    summary: str = ""       # one-paragraph overall assessment
    verdict: str = "proceed"  # "proceed" | "needs_work" | "reject"

    @classmethod
    def from_dict(cls, d: dict) -> "RequirementsEvaluation":
        return cls(
            clarity=d.get("clarity", 3),
            completeness=d.get("completeness", 3),
            feasibility=d.get("feasibility", 3),
            risks=d.get("risks", []),
            suggestions=d.get("suggestions", []),
            summary=d.get("summary", ""),
            verdict=d.get("verdict", "proceed"),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def overall_score(self) -> float:
        return (self.clarity + self.completeness + self.feasibility) / 3.0

    @property
    def has_risks(self) -> bool:
        return len(self.risks) > 0


# ── Communication ──────────────────────────────────────────────────────────────

@dataclass
class Message:
    """A single communication between persons, or from the system."""
    sender: str             # person_id or "system"
    recipient: str          # person_id, "team", or "orchestrator"
    kind: str               # "brief", "task", "result", "review", "question", "answer", "system"
    content: str
    context: dict = field(default_factory=dict)   # metadata: task_id, reason, etc.
    id: str = field(default_factory=_msg_id)
    timestamp: str = field(default_factory=_now)

    @classmethod
    def from_dict(cls, d: dict) -> "Message":
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
    def system(cls, recipient: str, content: str, **ctx) -> "Message":
        """Create a system message (e.g. rule violation feedback)."""
        return cls(sender="system", recipient=recipient, kind="system",
                   content=content, context=ctx)


@dataclass
class SessionRules:
    """Communication rules for a session — Persons are made aware of these."""
    pattern: str = "lead_delegates"     # communication pattern name
    max_rounds: int = 3                 # max back-and-forth exchanges
    allow_direct: bool = True           # can members message each other?
    channels: list = field(default_factory=list)  # allowed direct pairs: [["a","b"], ...]

    @classmethod
    def from_dict(cls, d: dict) -> "SessionRules":
        return cls(
            pattern=d.get("pattern", "lead_delegates"),
            max_rounds=d.get("max_rounds", 3),
            allow_direct=d.get("allow_direct", True),
            channels=d.get("channels", []),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    def describe(self, participant_id: str, all_participants: list[str]) -> str:
        """Produce a human-readable summary of rules for a participant."""
        others = [p for p in all_participants if p != participant_id]
        lines = [
            f"Communication rules for this session:",
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
                if my_peers:
                    lines.append(f"- You may message directly: {', '.join(my_peers)}")
                else:
                    lines.append("- You may not send direct messages to others")
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
    participants: list[str]          # person_ids
    rules: SessionRules = field(default_factory=SessionRules)
    messages: list[Message] = field(default_factory=list)
    round: int = 0
    status: str = "active"           # "active" | "complete" | "terminated"

    def can_send(self, sender: str, recipient: str) -> tuple[bool, str]:
        """Check if a message is allowed. Returns (allowed, reason)."""
        if self.status != "active":
            return False, f"Session is {self.status}"

        if self.round >= self.rules.max_rounds:
            return False, f"Max rounds ({self.rules.max_rounds}) reached"

        if sender not in self.participants and sender != "system":
            return False, f"{sender} is not a participant in this session"

        if recipient not in self.participants and recipient not in ("team", "orchestrator", "system"):
            return False, f"{recipient} is not a participant in this session"

        if not self.rules.allow_direct and sender != "system":
            # Only lead or system can broadcast — others must go through lead
            # (enforced by pattern, not here — this is the general channel check)
            pass

        if self.rules.channels and sender != "system":
            pair_allowed = (
                [sender, recipient] in self.rules.channels or
                [recipient, sender] in self.rules.channels
            )
            # Lead can always talk to anyone
            lead_involved = False  # caller should check this if needed
            if not pair_allowed and self.rules.allow_direct:
                return False, f"No direct channel between {sender} and {recipient}"

        return True, ""

    def add_message(self, msg: Message) -> Message | None:
        """
        Try to add a message to the session.
        Returns None if allowed, or a system feedback Message if blocked.
        """
        allowed, reason = self.can_send(msg.sender, msg.recipient)
        if not allowed:
            self.messages.append(msg)  # log the attempt
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
        """Increment the round counter."""
        self.round += 1

    def complete(self) -> None:
        self.status = "complete"

    def is_complete(self) -> bool:
        return self.status != "active" or self.round >= self.rules.max_rounds

    def messages_for(self, person_id: str) -> list[Message]:
        """Get all messages a person has received (including system)."""
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
    def from_dict(cls, d: dict) -> "Session":
        return cls(
            id=d["id"],
            task_id=d["task_id"],
            participants=d.get("participants", []),
            rules=SessionRules.from_dict(d.get("rules", {})),
            messages=[Message.from_dict(m) for m in d.get("messages", [])],
            round=d.get("round", 0),
            status=d.get("status", "active"),
        )
