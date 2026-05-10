from __future__ import annotations

from dataclasses import dataclass, field

from ._utils import _now
from .requirements import Requirement, SubRequirement

_MIN_SPEC_LENGTH = 50
MAX_PLAN_DEPTH = 20


@dataclass
class TaskInput:
    """
    The input handed to a team so they can create a Plan.

    specification: what needs to be done at this level — validated before planning.
    context:       higher-level background from the parent plan — not validated,
                   gives the team alignment with the broader structure.
    """
    specification: str
    context: str = ""

    def validate(self) -> list[str]:
        """Validate specification only. context is informational and never validated."""
        errors = []
        if not self.specification or not self.specification.strip():
            errors.append("Specification is empty.")
            return errors
        stripped = self.specification.strip()
        if len(stripped) < _MIN_SPEC_LENGTH:
            errors.append(
                f"Specification too short ({len(stripped)} chars). "
                f"Minimum {_MIN_SPEC_LENGTH} characters needed."
            )
        try:
            stripped.encode("utf-8")
        except UnicodeEncodeError:
            errors.append("Specification contains non-text content.")
            return errors
        if "\x00" in stripped:
            errors.append("Specification appears to be binary (contains null bytes).")
        return errors

    @classmethod
    def from_dict(cls, d: dict) -> TaskInput:
        return cls(
            specification=d.get("specification", d.get("text", "")),
            context=d.get("context", ""),
        )

    def to_dict(self) -> dict:
        return {"specification": self.specification, "context": self.context}


@dataclass
class TaskStub:
    """
    Minimal task entry stored in a parent plan.yaml.

    Full task input and requirements live in tasks/{id}/plan.yaml on disk.
    depended_on_by is the reverse index of depends_on — tasks that wait for this one.
    """
    id: str
    title: str
    assigned_team: str
    depends_on: list = field(default_factory=list)
    depended_on_by: list = field(default_factory=list)
    is_checkpoint: bool = False
    status: str = "pending"
    output_file: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> TaskStub:
        return cls(
            id=d["id"],
            title=d["title"],
            assigned_team=d.get("assigned_team", ""),
            depends_on=d.get("depends_on", []),
            depended_on_by=d.get("depended_on_by", []),
            is_checkpoint=d.get("is_checkpoint", False),
            status=d.get("status", "pending"),
            output_file=d.get("output_file", ""),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "assigned_team": self.assigned_team,
            "depends_on": self.depends_on,
            "depended_on_by": self.depended_on_by,
            "is_checkpoint": self.is_checkpoint,
            "status": self.status,
            "output_file": self.output_file,
        }


@dataclass
class Plan:
    """
    Plan for any node in the task tree — identical structure at all depths.

    id:            project_id at the root node; task_id at every other depth.
    tasks:         list of TaskStub — lightweight references to child tasks.
                   Full child plans live in tasks/{id}/plan.yaml on disk.
    has_subtasks:  True → this node is composite; False → leaf (team executes directly).
    """
    id: str
    title: str
    input: TaskInput
    requirements: list = field(default_factory=list)
    tasks: list = field(default_factory=list)   # list[TaskStub]
    tech_stack: list = field(default_factory=list)
    teams_required: list = field(default_factory=list)
    status: str = "pending"
    created_at: str = field(default_factory=_now)
    decisions_log: list = field(default_factory=list)

    @property
    def has_subtasks(self) -> bool:
        return len(self.tasks) > 0

    @classmethod
    def from_dict(cls, d: dict, _depth: int = 0) -> Plan:
        if _depth > MAX_PLAN_DEPTH:
            raise ValueError(
                f"Plan nesting exceeds maximum depth ({MAX_PLAN_DEPTH}). "
                "Check for circular references in plan data."
            )
        if "input" in d and isinstance(d["input"], dict):
            plan_input = TaskInput.from_dict(d["input"])
        else:
            plan_input = TaskInput(specification=d.get("requirements_text", ""))
        # Support both "id" (new) and "project_id" (legacy) keys
        plan_id = d.get("id", d.get("project_id", ""))
        return cls(
            id=plan_id,
            title=d.get("title", ""),
            input=plan_input,
            requirements=[Requirement.from_dict(r) for r in d.get("requirements", [])],
            tasks=[TaskStub.from_dict(t) for t in d.get("tasks", [])],
            tech_stack=d.get("tech_stack", []),
            teams_required=d.get("teams_required", []),
            status=d.get("status", "pending"),
            created_at=d.get("created_at", _now()),
            decisions_log=d.get("decisions_log", []),
        )

    def to_dict(self, _depth: int = 0) -> dict:
        if _depth > MAX_PLAN_DEPTH:
            raise ValueError(
                f"Plan nesting exceeds maximum depth ({MAX_PLAN_DEPTH}). "
                "Check for circular references in plan data."
            )
        return {
            "id": self.id,
            "title": self.title,
            "input": self.input.to_dict(),
            "requirements": [r.to_dict() for r in self.requirements],
            "tasks": [t.to_dict() for t in self.tasks],
            "tech_stack": self.tech_stack,
            "teams_required": self.teams_required,
            "status": self.status,
            "created_at": self.created_at,
            "decisions_log": self.decisions_log,
        }

    def task_by_id(self, task_id: str) -> TaskStub | None:
        """Return the TaskStub with the given id, or None."""
        for stub in self.tasks:
            if stub.id == task_id:
                return stub
        return None

    def requirement_by_id(self, req_id: str) -> Requirement | None:
        for r in self.requirements:
            if r.id == req_id:
                return r
        return None

    def sub_requirement_by_id(self, sub_id: str) -> SubRequirement | None:
        for r in self.requirements:
            for s in r.sub_requirements:
                if s.id == sub_id:
                    return s
        return None


ProjectPlan = Plan
