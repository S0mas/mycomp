from __future__ import annotations

from dataclasses import dataclass, field, asdict

from ._utils import _now


@dataclass
class SubRequirement:
    """One decomposed slice of a top-level Requirement, linked to acceptance criteria."""
    id: str
    parent_id: str
    title: str
    description: str
    acceptance_criteria: list = field(default_factory=list)
    status: str = "pending"

    @classmethod
    def from_dict(cls, d: dict) -> SubRequirement:
        return cls(
            id=d["id"],
            parent_id=d.get("parent_id", ""),
            title=d["title"],
            description=d.get("description", ""),
            acceptance_criteria=d.get("acceptance_criteria", []),
            status=d.get("status", "pending"),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Requirement:
    """A top-level requirement that can be decomposed into sub-requirements."""
    id: str
    title: str
    description: str
    sub_requirements: list = field(default_factory=list)
    status: str = "pending"

    @classmethod
    def from_dict(cls, d: dict) -> Requirement:
        subs = [SubRequirement.from_dict({**s, "parent_id": d["id"]})
                for s in d.get("sub_requirements", [])]
        return cls(
            id=d["id"],
            title=d["title"],
            description=d.get("description", ""),
            sub_requirements=subs,
            status=d.get("status", "pending"),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "sub_requirements": [s.to_dict() for s in self.sub_requirements],
            "status": self.status,
        }
