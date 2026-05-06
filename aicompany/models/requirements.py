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

    def all_sub_ids(self) -> list[str]:
        return [s.id for s in self.sub_requirements]


@dataclass
class RequirementTest:
    """A pytest test file that proves a specific sub-requirement is met."""
    id: str
    sub_req_id: str
    title: str
    test_file: str
    status: str = "pending"

    @classmethod
    def from_dict(cls, d: dict) -> RequirementTest:
        return cls(
            id=d["id"],
            sub_req_id=d["sub_req_id"],
            title=d["title"],
            test_file=d.get("test_file", ""),
            status=d.get("status", "pending"),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RequirementTestSuite:
    """Groups all RequirementTests for a single top-level Requirement."""
    id: str
    requirement_id: str
    name: str
    test_ids: list = field(default_factory=list)
    status: str = "pending"

    @classmethod
    def from_dict(cls, d: dict) -> RequirementTestSuite:
        return cls(
            id=d["id"],
            requirement_id=d["requirement_id"],
            name=d["name"],
            test_ids=d.get("test_ids", []),
            status=d.get("status", "pending"),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RequirementsEvaluation:
    """Structured assessment of a requirements document before planning."""
    clarity: int
    completeness: int
    feasibility: int
    risks: list = field(default_factory=list)
    suggestions: list = field(default_factory=list)
    summary: str = ""
    verdict: str = "proceed"

    @classmethod
    def from_dict(cls, d: dict) -> RequirementsEvaluation:
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
        return bool(self.risks)
