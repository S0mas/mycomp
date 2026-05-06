# Communication patterns

Agents collaborate through structured message sessions. `communication.py` creates sessions
and dispatches to a named pattern. `patterns.py` implements the actual message choreography.

---

## Session lifecycle

```plantuml
@startuml
[*] --> active : create_session()

active --> active : add_message() [can_send passes]
active --> active : advance_round()

active --> complete : session.complete()
active --> complete : round >= max_rounds\n(is_complete() returns True)

complete --> [*]
@enduml
```

**`Session.can_send(sender, recipient)`** checks (all must pass):
1. `status == "active"`
2. `round < max_rounds`
3. `sender` is a participant or system actor
4. `recipient` is a participant or system actor
5. If `channels` defined: pair must be in channels list

**`Session.messages_for(person_id)`** returns messages where:
- `recipient == person_id` (addressed to this person), OR
- `recipient == "team"` (broadcast), OR
- `sender == person_id` (own messages, for context)

---

## Pattern selection

The team's `communication` dict (from YAML) → `SessionRules` → `rules.pattern`:

```
"lead_delegates"     → run_lead_delegates()
"pair_review"        → run_pair_review()
"develop_test_review"→ run_develop_test_review()
(unknown)            → falls back to run_lead_delegates()
```

---

## Pattern 1: `lead_delegates`

Default pattern. Works with any team size. Lead coordinates; members produce; lead synthesizes.

```plantuml
@startuml
participant "Orchestrator" as Orch
participant "Lead" as Lead
participant "Member 1" as M1
participant "Member 2" as M2

Orch -> Lead : task (brief request + context + team roster)
Lead -> Lead : think() → brief
Lead -> "Team" : brief (broadcast)
note right : session.advance_round()

M1 -> M1 : think() → contribution
M1 -> Lead : result

M2 -> M2 : think() → contribution
M2 -> Lead : result
note right : session.advance_round()

Lead -> Lead : think() → synthesis\n(incorporating all contributions)
Lead -> Orch : result (final output)
note right : session.complete()
@enduml
```

Special case: if team has only the lead (no other members), the brief IS the output — no
synthesis round.

---

## Pattern 2: `pair_review`

For teams with a reviewer. Used by CTO team and any HR-created team with a reviewer role.

**With coder + reviewer** (full pair_review):

```plantuml
@startuml
participant "Orchestrator" as Orch
participant "Lead" as Lead
participant "Coder" as Coder
participant "Reviewer" as Rev

Orch -> Lead : task
Lead -> Lead : think() → brief
Lead -> "Team" : brief
note right : advance_round()

Coder -> Coder : think() → implementation
Coder -> Rev : result
note right : advance_round()

Rev -> Rev : think() → review
Rev -> Coder : review

opt session not complete
  note right : advance_round()
  Coder -> Coder : think() → revision
  Coder -> Lead : result
end

Lead -> Lead : think() → finalize
Lead -> Orch : result
note right : session.complete()
@enduml
```

**With reviewer but no coder** (lead-as-producer mode — used by CTO team):

```plantuml
@startuml
participant "Orchestrator" as Orch
participant "Lead" as Lead
participant "Reviewer" as Rev

Orch -> Lead : task
Lead -> Lead : think() → initial draft
Lead -> Rev : draft (result)
note right : advance_round()

Rev -> Rev : think() → review
Rev -> Lead : review

opt session not complete
  note right : advance_round()
  Lead -> Lead : think() → revision
end

Lead -> Orch : result (final)
note right : session.complete()
@enduml
```

**No reviewer** → falls back to `lead_delegates`.

---

## Pattern 3: `develop_test_review`

For teams with coder + tester + reviewer. Full TDD cycle with requirements traceability.

```plantuml
@startuml
participant "Orchestrator" as Orch
participant "Lead" as Lead
participant "Coder" as Coder
participant "Tester" as Tester
participant "Reviewer" as Rev

Orch -> Lead : task
Lead -> Lead : think() → brief
Lead -> "Team" : brief
note right : advance_round()

Coder -> Coder : think() → implementation\n(code files via MCP write_file)
Coder -> Tester : result
note right : advance_round()

Tester -> Tester : think() → requirement tests\n(test files via MCP write_file)
Tester -> Rev : test results

opt session not complete
  note right : advance_round()
  Rev -> Rev : think() → review\n(code + tests)
  Rev -> Coder : review
  
  opt session not complete
    note right : advance_round()
    Coder -> Coder : think() → revision
    Coder -> Lead : revised result
  end
end

Lead -> Lead : think() → final synthesis\nwith traceability summary
Lead -> Orch : result
note right : session.complete()
@enduml
```

**Fallback chain**:
- No tester → `pair_review`
- No coder or reviewer → `lead_delegates`

---

## Workspace file writing

When `workspace` is set (non-empty), `_agent_rules()` appends file-writing instructions
to every person's session rules:

```
## File output
Workspace: `projects/<id>/src`
Write every implementation file using the write_file MCP tool.
Read existing files with read_file. Run tests/commands with run_command.
```

Agents call the MCP `write_file` tool from within their LLM response. Files appear in
`projects/<id>/src/` on the host filesystem.

---

## Adding a new pattern

1. Add `run_my_pattern(session, lead, members, ...) -> str` to `patterns.py`
2. Follow the same signature as the existing patterns
3. Add it to the `PATTERNS` dict at the bottom of `patterns.py`
4. Set `communication.pattern = "my_pattern"` in the team YAML
5. Add a test in `tests/test_communication.py`
