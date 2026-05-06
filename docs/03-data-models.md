# Data Models

All models live in `aicompany/models/` and are pure dataclasses — no I/O, no LLM calls.
Every model implements `to_dict() / from_dict()` for YAML/JSON serialisation.

---

## 1. Organisation models (`models/org.py`)

```plantuml
@startuml
skinparam classAttributeIconSize 0

class Skill {
  + id: str
  + name: str
  + category: str
  + knowledge: list[str]
  + created_at: str
  --
  + from_dict(d) : Skill
  + to_dict() : dict
}

class Person {
  + id: str
  + name: str
  + role: str
  + identity: str
  + skills: list[str]
  + knowledge: list[str]
  + rules: list[str]
  + tools: list[str]
  + created_at: str
  --
  + from_dict(d) : Person
  + to_dict() : dict
}

class Team {
  + id: str
  + name: str
  + skills: list[str]
  + members: list[str]
  + lead_id: str
  + communication: dict
  + created_at: str
  --
  + skill_set: set[str]
  + from_dict(d) : Team
  + to_dict() : dict
}

class CompanyState {
  + version: str
  + created_at: str
  + teams: list[dict]
  + persons: list[dict]
  + skills: list[dict]
  + technologies_seen: list[str]
  --
  + team_ids() : list[str]
  + person_ids() : list[str]
  + skill_ids() : list[str]
  + all_skills() : set[str]
  + from_dict(d) : CompanyState
  + to_dict() : dict
}

Person "references" --> Skill : skills[] IDs
Team "references" --> Person : members[] IDs\nlead_id
CompanyState "indexes" --> Team : slim dicts
CompanyState "indexes" --> Person : slim dicts
CompanyState "indexes" --> Skill : slim dicts

note right of Team::communication
  dict with keys:
    pattern: str
    max_rounds: int
end note

note right of Person::role
  Expected values for
  pattern routing:
  lead | coder | reviewer | tester
end note
@enduml
```

**`build_prompt(person, skill_registry)`** (free function in org.py): Composes the system
prompt for an LLM call from `person.identity + skill.knowledge + person.knowledge + person.rules`.

---

## 2. Project models (`models/project.py`)

```plantuml
@startuml
skinparam classAttributeIconSize 0

class TaskInput {
  + specification: str
  + context: str
  --
  + validate() : list[str]
  + from_dict(d) : TaskInput
  + to_dict() : dict
}

note right of TaskInput::specification
  Validated: ≥ 50 chars,
  valid UTF-8, no null bytes.
  Describes what to build.
end note

note right of TaskInput::context
  Parent project background.
  Not validated. Never shown
  to validators.
end note

class Task {
  + id: str
  + title: str
  + input: TaskInput
  + assigned_team: str
  + plan: Plan
  + depends_on: list[str]
  + status: str
  + is_checkpoint: bool
  + output_file: str
  --
  + from_dict(_depth) : Task
  + to_dict(_depth) : dict
}

class Plan {
  + project_id: str
  + title: str
  + input: TaskInput
  + requirements: list[Requirement]
  + tasks: list[Task]
  + tech_stack: list[str]
  + teams_required: list[str]
  + status: str
  + created_at: str
  + decisions_log: list[dict]
  --
  + has_subtasks: bool
  + task_by_id(id) : Task
  + requirement_by_id(id) : Requirement
  + sub_requirement_by_id(id) : SubRequirement
  + from_dict(_depth) : Plan
  + to_dict(_depth) : dict
}

Plan "contains" *-- Task : tasks[]
Task "contains" *-- Plan : plan (recursive)
Task "contains" *-- TaskInput : input
Plan "contains" *-- TaskInput : input

note right of Plan::has_subtasks
  True when tasks[] is non-empty.
  False = leaf plan (execute team directly).
  True = composite (recurse into sub-tasks).
end note

note right of Plan
  MAX_PLAN_DEPTH = 20
  Depth tracked via _depth param
  in from_dict/to_dict to prevent
  infinite recursion.
end note
@enduml
```

**Task status lifecycle**: `pending` → `running` → `done` | `failed`

---

## 3. Session models (`models/session.py`)

```plantuml
@startuml
skinparam classAttributeIconSize 0

class Message {
  + sender: str
  + recipient: str
  + kind: str
  + content: str
  + context: dict
  + id: str
  + timestamp: str
  --
  + system(recipient, content, **ctx) : Message
  + from_dict(d) : Message
  + to_dict() : dict
}

class SessionRules {
  + pattern: str
  + max_rounds: int
  + allow_direct: bool
  + channels: list
  --
  + describe(participant_id, all_participants) : str
  + from_dict(d) : SessionRules
  + to_dict() : dict
}

class Session {
  + id: str
  + task_id: str
  + participants: list[str]
  + rules: SessionRules
  + messages: list[Message]
  + round: int
  + status: str
  --
  + can_send(sender, recipient) : (bool, str)
  + add_message(msg) : Message | None
  + advance_round() : None
  + complete() : None
  + is_complete() : bool
  + messages_for(person_id) : list[Message]
  + from_dict(d) : Session
  + to_dict() : dict
}

Session "contains" *-- SessionRules : rules
Session "contains" *-- Message : messages[]

note right of Message::kind
  task | brief | result |
  review | system
end note

note right of Message::sender
  person_id | "system" |
  "orchestrator" | "team"
end note

note right of Session::messages_for
  Returns messages where:
  recipient == person_id OR
  recipient == "team" OR
  sender == person_id
end note

note right of SessionRules::channels
  Optional list of allowed pairs:
  [["alice","bob"],["bob","lead"]]
  Empty = all pairs allowed.
end note
@enduml
```

**`Session.can_send` rules** (all must pass):
1. Session is `"active"`
2. Round < `max_rounds`
3. Sender is a participant (or `"orchestrator"/"system"`)
4. Recipient is a participant (or `"team"/"orchestrator"/"system"`)
5. If `channels` defined: sender–recipient pair must be in `channels`

---

## 4. Requirements models (`models/requirements.py`)

```plantuml
@startuml
skinparam classAttributeIconSize 0

class SubRequirement {
  + id: str
  + parent_id: str
  + title: str
  + description: str
  + acceptance_criteria: list[str]
  + status: str
  --
  + from_dict(d) : SubRequirement
  + to_dict() : dict
}

class Requirement {
  + id: str
  + title: str
  + description: str
  + sub_requirements: list[SubRequirement]
  + status: str
  --
  + all_sub_ids() : list[str]
  + requirement_by_id(id) : SubRequirement | None
  + from_dict(d) : Requirement
  + to_dict() : dict
}

class RequirementTest {
  + id: str
  + sub_req_id: str
  + title: str
  + test_file: str
  + status: str
  --
  + from_dict(d) : RequirementTest
  + to_dict() : dict
}

class RequirementTestSuite {
  + id: str
  + requirement_id: str
  + name: str
  + test_ids: list[str]
  + status: str
  --
  + from_dict(d) : RequirementTestSuite
  + to_dict() : dict
}

class RequirementsEvaluation {
  + clarity: int
  + completeness: int
  + feasibility: int
  + risks: list[str]
  + suggestions: list[str]
  + summary: str
  + verdict: str
  --
  + overall_score: float
  + has_risks: bool
  + from_dict(d) : RequirementsEvaluation
  + to_dict() : dict
}

Requirement "contains" *-- SubRequirement : sub_requirements[]
RequirementTest "traces" --> SubRequirement : sub_req_id
RequirementTestSuite "groups" --> RequirementTest : test_ids[]
RequirementTestSuite "covers" --> Requirement : requirement_id

note right of Requirement::id
  Format: REQ-0001
end note

note right of SubRequirement::id
  Format: REQ-0001-001
end note

note right of RequirementsEvaluation::overall_score
  average(clarity, completeness, feasibility)
  Must be ≥ 3.5 to proceed.
  Each dimension must be ≥ 3.
end note
@enduml
```

---

## Disk layout

```
company/
  state.yaml               ← CompanyState (slim index of all entities)
  teams/<team_id>.yaml     ← Team
  persons/<person_id>.yaml ← Person
  skills/<skill_id>.yaml   ← Skill

projects/<project_id>/
  plan.yaml                ← Plan (with nested Tasks)
  requirements.md          ← raw requirements text
  req_tests/
    _requirements.yaml     ← list[Requirement]
    <req_test_id>.yaml     ← RequirementTest
  test_suites/
    <suite_id>.yaml        ← RequirementTestSuite
  outputs/<task_id>.md     ← agent output text
  sessions/<task_id>.json  ← Session (message log)
  decisions/<ts>_<t>.md    ← human decision records
```
