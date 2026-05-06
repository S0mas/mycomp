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
class Plan:
    """
    The plan for the Task that owns it — created by a team from TaskInput.

    Detailed about the owning task (input + requirements).
    High-level about subtasks (if any) — each subtask owns its own Plan.

    has_subtasks == False: task is executed directly by its assigned_team.
    has_subtasks == True:  task is realized by executing plan.tasks in order.

    Serialization passes _depth through to_dict/from_dict to enforce MAX_PLAN_DEPTH
    and catch circular references without silently overflowing the call stack.
    """
    project_id: str
    title: str
    input: TaskInput
    requirements: list = field(default_factory=list)
    tasks: list = field(default_factory=list)
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
        return cls(
            project_id=d.get("project_id", ""),
            title=d.get("title", ""),
            input=plan_input,
            requirements=[Requirement.from_dict(r) for r in d.get("requirements", [])],
            tasks=[Task.from_dict(t, _depth + 1) for t in d.get("tasks", [])],
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
            "project_id": self.project_id,
            "title": self.title,
            "input": self.input.to_dict(),
            "requirements": [r.to_dict() for r in self.requirements],
            "tasks": [t.to_dict(_depth + 1) for t in self.tasks],
            "tech_stack": self.tech_stack,
            "teams_required": self.teams_required,
            "status": self.status,
            "created_at": self.created_at,
            "decisions_log": self.decisions_log,
        }

    def task_by_id(self, task_id: str) -> Task | None:
        """Iterative BFS — avoids recursive descent into arbitrarily deep plan trees."""
        queue = list(self.tasks)
        while queue:
            task = queue.pop(0)
            if task.id == task_id:
                return task
            if task.plan.has_subtasks:
                queue.extend(task.plan.tasks)
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


@dataclass
class Task:
    """
    A unit of work at any level of the hierarchy.

    input: what this task needs to accomplish + parent context for alignment.
    plan:  always present — detailed about this task, high-level about subtasks.
    """
    id: str
    title: str
    input: TaskInput
    assigned_team: str
    plan: Plan
    depends_on: list = field(default_factory=list)
    status: str = "pending"
    is_checkpoint: bool = False
    output_file: str = ""

    @classmethod
    def from_dict(cls, d: dict, _depth: int = 0) -> Task:
        if _depth > MAX_PLAN_DEPTH:
            raise ValueError(
                f"Task nesting exceeds maximum depth ({MAX_PLAN_DEPTH}). "
                "Check for circular references in plan data."
            )
        if "input" in d and isinstance(d["input"], dict):
            task_input = TaskInput.from_dict(d["input"])
        else:
            task_input = TaskInput(specification=d.get("description", ""))

        if "plan" in d and isinstance(d["plan"], dict):
            task_plan = Plan.from_dict(d["plan"], _depth)
        else:
            task_plan = Plan(
                project_id="",
                title=d.get("title", ""),
                input=task_input,
                requirements=[],
                tasks=[],
            )

        return cls(
            id=d["id"],
            title=d["title"],
            input=task_input,
            assigned_team=d["assigned_team"],
            plan=task_plan,
            depends_on=d.get("depends_on", []),
            status=d.get("status", "pending"),
            is_checkpoint=d.get("is_checkpoint", False),
            output_file=d.get("output_file", ""),
        )

    def to_dict(self, _depth: int = 0) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "input": self.input.to_dict(),
            "assigned_team": self.assigned_team,
            "plan": self.plan.to_dict(_depth),
            "depends_on": self.depends_on,
            "status": self.status,
            "is_checkpoint": self.is_checkpoint,
            "output_file": self.output_file,
        }


ProjectPlan = Plan
