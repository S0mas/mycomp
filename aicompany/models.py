from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    created_at: str = field(default_factory=_now)

    @classmethod
    def from_dict(cls, d: dict) -> "Team":
        return cls(
            id=d["id"],
            name=d["name"],
            skills=d.get("skills", []),
            members=d.get("members", []),
            lead_id=d.get("lead_id", ""),
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
