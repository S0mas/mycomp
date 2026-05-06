# New-project flow

`./mycomp new-project requirements.md` evaluates requirements, runs the CTO team to plan
the project, creates any missing teams via HR, and saves a ready-to-run project plan.

---

## Full sequence

```plantuml
@startuml
actor Developer
participant "cli.py" as CLI
participant "validation.py" as Val
participant "evaluation.py" as Eval
participant "llm.py" as LLM
participant "planning.py" as Plan
participant "communication.py\npatterns.py" as Comm
participant "registry.py" as Reg
participant "Claude API" as API

Developer -> CLI : new-project requirements.md

== Validation ==
CLI -> Val : validate_requirements_text(text)
Val --> CLI : errors (if any → exit 1)

== Requirements evaluation ==
CLI -> Eval : evaluate_and_gate(text)
Eval -> Reg : load_state()
Eval -> LLM : evaluate_requirements(text, state_yaml)
LLM -> API : call(eval_system.txt prompt)
API --> LLM : {clarity, completeness, feasibility, risks, verdict}
LLM --> Eval : RequirementsEvaluation
Eval --> CLI : EvaluationResult

alt blocked (score < threshold or verdict=reject)
  CLI --> Developer : show blockers + offer autofix
  opt autofix
    CLI -> Eval : autofix_requirements(text, eval_dict)
    Eval -> LLM : autofix prompt
    LLM -> API : call(autofix_system.txt)
    API --> LLM : improved Markdown
    CLI --> Developer : save {name}_fixed.md → exit 1
  end
else proceed
  CLI --> Developer : ✓ passed evaluation
end

== CTO planning ==
CLI -> Plan : plan_and_create_project(text)
Plan -> Reg : load_state() → state_yaml
Plan -> Comm : run_pattern("pair_review", cto_team, ...)
note right of Comm
  See CTO pair_review sub-flow below
end note
Comm --> Plan : CTO output text
Plan -> LLM : extract_json_block(cto_output)
LLM --> Plan : plan_dict

Plan -> Val : validate_cto_plan(plan_dict)
Val --> Plan : warnings (non-blocking)

== HR team creation ==
Plan -> Reg : load_state()
loop for each missing team_id
  Plan -> LLM : hr_create_team(team_id, tech_context)
  LLM -> API : call(hr_system.txt)
  API --> LLM : {team, persons, skills}
  Plan -> Val : validate_hr_response(result, team_id)
  Plan -> Reg : save_skill() × N
  Plan -> Reg : save_person() × N
  Plan -> Reg : save_team()
end

Plan -> Reg : _update_technologies(tech_stack)

== Project assembly ==
Plan -> Plan : _assemble_project(...)
note right of Plan
  Pure transformation:
  raw_tasks → Task objects
  with TaskInput + scoped Plan
end note
Plan -> Reg : create_project_dir(project_id, requirements_text)
Plan -> Reg : save_plan(plan)
Plan -> Reg : save_requirements(project_id, requirements)
Plan --> CLI : PlanResult

CLI --> Developer : ✓ Project created: proj_<id>
@enduml
```

---

## CTO pair_review sub-flow

The CTO team uses the `pair_review` pattern. Since the team has a lead (CTO) and reviewer
(analyst) but no dedicated coder, the **lead acts as producer** (see [08-communication.md](08-communication.md)):

```plantuml
@startuml
participant "Orchestrator\n(planning.py)" as Orch
participant "CTO\n(lead)" as CTO
participant "Technical Analyst\n(reviewer)" as Analyst

Orch -> CTO : task message\n(requirements + state YAML)
CTO -> CTO : think() → initial plan JSON
CTO -> Analyst : result (plan draft)
Analyst -> Analyst : think() → review notes
Analyst -> CTO : review (issues + verdict)

alt session not complete
  CTO -> CTO : think() → revised plan JSON
end

CTO -> Orch : final plan text (JSON block)
@enduml
```

CTO rules enforce: output ONLY a JSON block with the exact schema (title, tech_stack,
teams_required, requirements, tasks). The analyst returns a Markdown review with verdict
`approve` or `request-changes`. The CTO then revises if needed.

---

## HR team creation sub-flow

```plantuml
@startuml
participant "planning.py" as Plan
participant "llm.py" as LLM
participant "Claude API" as API
participant "validation.py" as Val
participant "registry.py" as Reg

Plan -> LLM : hr_create_team(team_id, tech_context)
LLM -> API : call(hr_system.txt)
API --> LLM : JSON: {team, persons, skills}
LLM --> Plan : result dict

Plan -> Val : validate_hr_response(result, team_id)
Val --> Plan : warnings (role checks, member definitions)

loop for each Skill in result.skills
  Plan -> Reg : save_skill(Skill.from_dict(sd))
end
loop for each Person in result.persons
  Plan -> Reg : save_person(Person.from_dict(pd))
end
Plan -> Reg : save_team(Team.from_dict(team_data))

note right of Plan
  registry.save_* auto-registers
  each entity in state.yaml
end note
@enduml
```

---

## Quality gate thresholds

| Check | Threshold | Location |
|-------|-----------|----------|
| Requirements minimum length | ≥ 50 chars | `validation.py` / `TaskInput.validate()` |
| Overall evaluation score | ≥ 3.5 / 5 | `config.MIN_SCORE_TO_PROCEED` |
| Each dimension (clarity/completeness/feasibility) | ≥ 3 / 5 | `config.MIN_DIMENSION_SCORE` |
| Verdict | must not be `"reject"` | `evaluation.py` |

---

## Outputs

| Artifact | Path | Created by |
|----------|------|------------|
| Project plan | `projects/<id>/plan.yaml` | `registry.save_plan` |
| Requirements | `projects/<id>/requirements.md` | `registry.create_project_dir` |
| Requirements YAML | `projects/<id>/req_tests/_requirements.yaml` | `registry.save_requirements` |
| New teams | `company/teams/<team>.yaml` | `registry.save_team` |
| New persons | `company/persons/<person>.yaml` | `registry.save_person` |
| New skills | `company/skills/<skill>.yaml` | `registry.save_skill` |
| Updated registry | `company/state.yaml` | auto on every save_* |
