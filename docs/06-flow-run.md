# Run flow

`./mycomp run <project-id>` loads the plan, sorts tasks by dependencies, and executes each
one — pausing at checkpoints for human approval. The loop is crash-safe: the plan is saved
after every task so a restart picks up where it left off.

---

## Topological sort (Kahn's algorithm)

Before any task runs, `_topological_sort(plan.tasks)` produces a dependency-safe execution
order:

```plantuml
@startuml
start
:Build in_degree map\n(task → count of unsatisfied deps);
:Build dependents map\n(task → list of tasks that depend on it);
:Enqueue all tasks with in_degree == 0;

while (queue not empty?) is (yes)
  :Dequeue task T;
  :Append T to result;
  :For each task D that depends on T:\n  decrement D.in_degree\n  if D.in_degree == 0: enqueue D;
endwhile

if (len(result) != len(tasks)) then (yes)
  :Raise OrchestratorError\n"Cycle detected";
  stop
else (no)
  :Return sorted task list;
  stop
endif
@enduml
```

Raises `OrchestratorError` on: unknown dependency IDs, dependency cycles.

---

## Main execution loop

```plantuml
@startuml
participant "orchestrator.py" as Orch
participant "oversight.py" as Over
participant "registry.py" as Reg

Orch -> Reg : load_plan(project_id)
Orch -> Orch : _topological_sort(plan.tasks)
Orch -> Orch : build completed_ids, failed_ids\n(from existing task.status)

loop for each task in sorted order

  alt task.status == "done"
    Orch -> Orch : [skip] already done
  else any dep in failed_ids
    Orch -> Orch : task.status = "failed"\n[skip] dependency failed
  else not all deps in completed_ids
    Orch -> Orch : raise OrchestratorError\n(should not happen)
  else

    Orch -> Reg : load_output(plan.project_id, each dep_id)\n→ _find_prior_output (all deps concatenated)

    alt task.is_checkpoint AND not dry_run
      Orch -> Over : checkpoint(task, prior_output, project_id)
      Over -> "Developer" : display task + prior output
      "Developer" -> Over : A (approve) / R (reject) / M (modify)
      Over -> Reg : save_decision(project_id, task_id, record)
      Over --> Orch : (action, modified_text)

      alt action == "rejected"
        Orch -> Orch : task.status = "failed"\n[skip]
      else action == "modified"
        Orch -> Orch : append override to\ntask.input.specification
      end
    end

    alt dry_run
      Orch -> Orch : [dry-run] print what would run\nadd to completed_ids
    else
      Orch -> Orch : task.status = "running"
      Orch -> Reg : save_plan (status=running)
      Orch -> Orch : _execute_task(task, plan, ...)
      Orch -> Reg : save_output(project_id, task_id, output)
      Orch -> Orch : task.status = "done"
      Orch -> Orch : add to completed_ids
      Orch -> Reg : save_plan
    end
  end

end

Orch -> Reg : plan.status = "complete"\nsave_plan
@enduml
```

---

## Checkpoint decision

```plantuml
@startuml
actor Developer
participant "oversight.py" as Over

Over -> Developer : Display task panel:\n  - task ID, title, team\n  - task specification\n  - prior output (truncated at 2000 chars)
Developer -> Over : Input: A / R / M

alt "A" (approved)
  Over --> Orch : ("approved", "")
else "R" (rejected)
  Over --> Orch : ("rejected", "")
  note right : task.status = "failed"\nall dependents also fail
else "M" (modified)
  Over -> Developer : Enter modified instructions\n(press Enter twice to finish)
  Developer -> Over : modified instructions text
  Over --> Orch : ("modified", text)
  note right : text appended to\ntask.input.specification
end
@enduml
```

---

## `_execute_task` call chain

```plantuml
@startuml
participant "_execute_task" as Exec
participant "registry.py" as Reg
participant "communication.py" as Comm
participant "reasoner.py" as Reas
participant "Claude API" as API

Exec -> Exec : task.plan.has_subtasks?\n→ yes: _execute_subtask_plan (recurse)\n→ no: continue below

Exec -> Reg : load_team_with_members(task.assigned_team)
Reg --> Exec : (team, lead, members[], skill_registry)

Exec -> Exec : SessionRules.from_dict(team.communication)
Exec -> Comm : create_session(task_id, participant_ids, rules)
Comm --> Exec : Session

Exec -> Reas : create_reasoner()
Reas --> Exec : LLMReasoner (or ChatSessionReasoner)
Exec -> Reas : reasoner.setup(members, skill_registry)

Exec -> Exec : _build_project_context(plan, completed_ids, workspace, task)
note right of Exec
  Context includes:
  - task.input.context (parent summary)
  - project title + tech stack
  - completed task titles
  - workspace path
  - scoped requirements + acceptance criteria
end note

Exec -> Comm : run_pattern(rules.pattern, session, lead, members, ...)
Comm --> Exec : output text (final agent response)

Exec -> Reg : save_session(project_id, session)
Exec --> "_execute_task caller" : output text
@enduml
```

---

## Nested sub-task execution

If `task.plan.has_subtasks == True`, `_execute_subtask_plan` is called instead of the
direct team call:

```
_execute_subtask_plan(sub_plan):
  sorted_subs = _topological_sort(sub_plan.tasks)
  for sub in sorted_subs:
    sub_output = _execute_task(sub, sub_plan, ...)
    registry.save_output(project_id, sub.id, sub_output)
    sub.status = "done"
  return "\n\n---\n\n".join(all_sub_outputs)
```

The aggregated output of all sub-tasks becomes the parent task's output.

---

## Crash-safe re-entry

The plan is saved after every task (`save_plan` called on every status change). On restart:

```
completed_ids = {t.id for t in plan.tasks if t.status == "done"}
failed_ids    = {t.id for t in plan.tasks if t.status == "failed"}
```

Tasks already `"done"` are skipped. Tasks whose dependencies failed are also skipped.
Execution resumes from the first unfinished, unblocked task.
