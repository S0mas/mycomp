# Plan Policy

This policy defines what makes a CTO-produced project plan acceptable for execution.
Edit this file to match your project standards — it is loaded by PlanValidation for every review.

---

## Traceability rules

- Every sub-requirement ID listed in the requirements must be referenced by at least one task
  via its `requirement_ids` field.
- No task may reference a requirement ID that does not appear in the requirements list.
- Orphaned tasks (tasks with empty `requirement_ids` and no clear justification) are a violation.

---

## Structural rules

- Task IDs must be unique and follow the `task_NNN` pattern (sequential integers).
- All IDs listed in `depends_on` must correspond to task IDs that exist in the plan.
- The dependency graph must be acyclic — no circular dependencies.
- Each task must have exactly one `assigned_team`.

---

## Scope rules

- No single task should span multiple teams or require more than one focused work session.
- Tasks that are too large must be flagged for recursive decomposition via the `subtasks` field.
- The `tech_stack` must be consistent with the technologies referenced in task descriptions.

---

## Automatic rejection triggers

Any of the following cause an automatic **rejected** verdict:

- A requirement ID referenced in tasks that does not exist in the requirements list.
- A dependency cycle (task A depends on task B which depends on task A).
- Duplicate task IDs.
- A task with no title or no description.
- Assigned team ID that is not snake_case.
