from __future__ import annotations

from dataclasses import dataclass, field, asdict

from ._utils import _now


@dataclass
class Skill:
    """Shared knowledge unit — reusable across persons."""
    id: str
    name: str
    category: str = ""
    knowledge: list = field(default_factory=list)
    created_at: str = field(default_factory=_now)

    @classmethod
    def from_dict(cls, d: dict) -> Skill:
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
    role: str
    identity: str
    skills: list = field(default_factory=list)
    knowledge: list = field(default_factory=list)
    rules: list = field(default_factory=list)
    tools: list = field(default_factory=list)
    created_at: str = field(default_factory=_now)

    @classmethod
    def from_dict(cls, d: dict) -> Person:
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
    skills: list
    members: list
    lead_id: str
    communication: dict = field(default_factory=dict)
    created_at: str = field(default_factory=_now)

    @classmethod
    def from_dict(cls, d: dict) -> Team:
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


@dataclass
class CompanyState:
    version: str = "1"
    created_at: str = field(default_factory=_now)
    teams: list = field(default_factory=list)
    persons: list = field(default_factory=list)
    skills: list = field(default_factory=list)
    technologies_seen: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> CompanyState:
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


def _build_section(header: str, items: list) -> str:
    lines = "\n".join(f"- {i}" for i in items)
    return f"{header}:\n{lines}"


def build_prompt(person: Person, skill_registry: dict[str, Skill] | None = None) -> str:
    """Compose a system prompt from a person's structured context and their skills."""
    sections = [person.identity] if person.identity else []

    skill_knowledge = []
    if skill_registry:
        for skill_id in person.skills:
            skill = skill_registry.get(skill_id)
            if skill and skill.knowledge:
                skill_knowledge.extend(skill.knowledge)

    if skill_knowledge:
        sections.append(_build_section("Technical knowledge", skill_knowledge))
    if person.knowledge:
        sections.append(_build_section("Your experience", person.knowledge))
    if person.rules:
        sections.append(_build_section("Rules you follow", person.rules))

    return "\n\n".join(sections)
