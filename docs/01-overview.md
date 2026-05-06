# Overview

mycomp is an AI-driven SDLC orchestrator. A developer writes requirements in plain Markdown;
the system turns them into a structured project plan, assembles specialized AI agent teams,
and executes every task — pausing for human approval at critical decisions.

---

## C4 Context

```plantuml
@startuml
!include https://raw.githubusercontent.com/plantuml-stdlib/C4-PlantUML/master/C4_Context.puml

Person(dev, "Developer", "Writes requirements,\napproves checkpoints")

System(mycomp, "mycomp", "AI-driven SDLC orchestrator.\nPlans, builds teams, executes tasks.")

System_Ext(claude_api, "Claude API\n(Anthropic)", "LLM inference for all\nagent roles")

System_Ext(mcp_server, "MCP Server", "File & shell tools\nexposed to Claude agents\nduring task execution")

Rel(dev, mycomp, "Provides requirements,\napproves checkpoints", "CLI")
Rel(mycomp, claude_api, "Agent reasoning calls", "HTTPS / Anthropic SDK")
Rel(mycomp, mcp_server, "Task workspace I/O", "HTTP / SSE")
Rel(mcp_server, mycomp, "File reads/writes,\ntest results", "HTTP / SSE")

@enduml
```

---

## Key concepts

| Concept | What it is |
|---------|------------|
| **Skill** | A domain of expertise (e.g. Python, FastAPI). Shared across persons. Carries technical facts that any holder of the skill knows. |
| **Person** | An AI agent. Has an identity (system prompt), a set of Skills, personal knowledge, and behavioral rules. |
| **Team** | A group of Persons with a designated lead. Has a `communication` setting that selects which collaboration pattern to use. |
| **Session** | A runtime container for one team's conversation on one task. Holds messages, rules, round counter. |
| **TaskInput** | The input handed to a team: `specification` (what to build) + `context` (parent project background). |
| **Task** | A unit of work. Has a `plan` (a nested Plan), `depends_on` list, an `assigned_team`, and optionally `is_checkpoint=True`. |
| **Plan** | A list of Tasks plus requirements, tech stack, and metadata. The top-level Plan is the project; each Task also has its own Plan (for sub-tasks). |
| **Checkpoint** | A task marked `is_checkpoint=True`. Execution pauses; the developer reviews the previous output and decides to approve, reject, or modify the task spec before it runs. |
| **Requirements** | Structured decomposition of client needs: `Requirement → SubRequirement → acceptance_criteria`. Each task is scoped to specific sub-requirements. |

---

## Three-command workflow

```
./mycomp init
    └─ Creates company/state.yaml
    └─ Seeds 13 shared skills
    └─ Creates CTO team (cto + cto_analyst)

./mycomp new-project requirements.md
    └─ Evaluates requirements (quality gate)
    └─ CTO team plans: title, tech stack, teams, tasks, requirements
    └─ HR creates any missing teams
    └─ Saves project plan to projects/<id>/plan.yaml

./mycomp run <project-id>
    └─ Loads plan, topological-sorts tasks
    └─ For each task: [checkpoint?] → execute team → save output
    └─ Agents write code/tests to projects/<id>/src/ via MCP
```

---

## File system after a complete run

```
company/
  state.yaml            ← registry: teams, persons, skills, technologies_seen
  teams/<team>.yaml
  persons/<person>.yaml
  skills/<skill>.yaml

projects/<project-id>/
  requirements.md       ← original requirements
  plan.yaml             ← full Plan (task statuses, decisions_log)
  src/                  ← code written by agents via MCP
  outputs/<task>.md     ← each team's final output text
  sessions/<task>.json  ← full message log per task
  decisions/<ts>_<t>.md ← checkpoint decision records
  req_tests/            ← parsed requirements + test file references
  test_suites/          ← RequirementTestSuite groups
```
