# Self-Improvement — How AI Company Learns

## Overview

AI Company is designed to get better over time. Knowledge is stored in
structured, composable layers — not as monolithic prompt strings. This
means the system can learn at the right level and share improvements
across all agents automatically.

---

## The Three Knowledge Layers

```
┌─────────────────────────────────────────────────────────┐
│                    SKILLS (shared)                       │
│                                                         │
│  company/skills/python.yaml                             │
│  company/skills/fastapi.yaml                            │
│  company/skills/docker.yaml                             │
│                                                         │
│  Technical knowledge that any person referencing         │
│  this skill should know. When updated, every person     │
│  with that skill gets smarter automatically.            │
├─────────────────────────────────────────────────────────┤
│                   PERSONS (individual)                   │
│                                                         │
│  company/persons/backend_coder.yaml                     │
│    identity:  "You are a senior Backend Engineer."      │
│    skills:    [python, fastapi, sqlalchemy]              │
│    knowledge: [personal experience items]                │
│    rules:     [how this person works]                    │
│                                                         │
│  Person-specific knowledge and behavioural rules.       │
│  Updated when a specific person needs to change.        │
├─────────────────────────────────────────────────────────┤
│                    TEAMS (composition)                    │
│                                                         │
│  company/teams/backend_team.yaml                        │
│    skills:  [python, fastapi, ...]                      │
│    members: [backend_lead, backend_coder, ...]          │
│    lead_id: backend_lead                                │
│                                                         │
│  Who works together. Updated when team structure        │
│  needs to change.                                       │
└─────────────────────────────────────────────────────────┘
```

---

## How Prompts Are Composed

At execution time, each person's system prompt is **built** from their
structured context — not stored as a static string.

```
┌──────────────────────────────────────────────────────┐
│           build_prompt(person, skill_registry)        │
│                                                      │
│  ┌────────────────────────────────────────────────┐  │
│  │  1. IDENTITY                                   │  │
│  │  "You are a senior Backend Engineer."          │  │
│  └────────────────────────────────────────────────┘  │
│                      ↓                               │
│  ┌────────────────────────────────────────────────┐  │
│  │  2. SKILL KNOWLEDGE (from all referenced       │  │
│  │     skills in the shared registry)             │  │
│  │                                                │  │
│  │  From python.yaml:                             │  │
│  │  - Use type hints on all function signatures   │  │
│  │  - Prefer pathlib over os.path                 │  │
│  │                                                │  │
│  │  From fastapi.yaml:                            │  │
│  │  - Use async def for route handlers            │  │
│  │  - Use Pydantic models for validation          │  │
│  └────────────────────────────────────────────────┘  │
│                      ↓                               │
│  ┌────────────────────────────────────────────────┐  │
│  │  3. PERSONAL KNOWLEDGE                         │  │
│  │  - Focus on implementation, not architecture   │  │
│  │  - Learned: always validate all inputs         │  │
│  └────────────────────────────────────────────────┘  │
│                      ↓                               │
│  ┌────────────────────────────────────────────────┐  │
│  │  4. RULES                                      │  │
│  │  - Write complete, runnable code               │  │
│  │  - No placeholders, no TODOs                   │  │
│  │  - Include error handling for external calls   │  │
│  └────────────────────────────────────────────────┘  │
│                                                      │
│              → final system prompt string            │
└──────────────────────────────────────────────────────┘
```

---

## Learning at the Right Level

When the system discovers something new, the question is: **where does it go?**

```
  ┌─────────────────────────────┐
  │     What was learned?       │
  └─────────────┬───────────────┘
                │
        ┌───────┴───────┐
        │               │
  Is it about a    Is it about a
  technology?      specific person?
        │               │
        ▼               ▼
  ┌───────────┐   ┌────────────────┐
  │  SKILL    │   │    PERSON      │
  │           │   │                │
  │ Update    │   │ Is it what     │
  │ knowledge │   │ they know?     │
  │ list      │   │     │          │
  │           │   │  ┌──┴──┐       │
  │ Everyone  │   │  │     │       │
  │ with this │   │  ▼     ▼       │
  │ skill     │   │ know-  rules   │
  │ benefits  │   │ ledge         │
  └───────────┘   └────────────────┘
```

### Examples

| What was learned | Where it goes | Who benefits |
|---|---|---|
| "FastAPI 0.110 changed dependency injection syntax" | `skills/fastapi.yaml` knowledge | Every person with `fastapi` skill |
| "Backend coder keeps forgetting input validation" | `persons/backend_coder.yaml` rules | Only backend_coder |
| "SQLAlchemy 2.0 uses select() not Query" | `skills/sqlalchemy.yaml` knowledge | All SQLAlchemy users |
| "This reviewer works best with explicit examples" | `persons/backend_reviewer.yaml` rules | Only backend_reviewer |
| "Always run migrations before deploying" | `skills/postgresql.yaml` knowledge | All PostgreSQL users |
| "Coder learned that connection pooling matters" | `persons/backend_coder.yaml` knowledge | Only backend_coder |

---

## The Self-Improvement Loop (Future)

The current system has the **structure** for learning but not yet the
**automation**. Here's the planned loop:

```
     ┌──────────────────────────────────────────────┐
     │                                              │
     │            THE IMPROVEMENT LOOP              │
     │                                              │
     │   ┌──────────┐     ┌─────────────────┐      │
     │   │  Project  │────▶│  Execute tasks  │      │
     │   │  starts   │     │  with current   │      │
     │   └──────────┘     │  knowledge      │      │
     │                     └────────┬────────┘      │
     │                              │               │
     │                              ▼               │
     │                     ┌─────────────────┐      │
     │                     │  Evaluate        │      │
     │                     │  outputs         │      │
     │                     │  (quality scores)│      │
     │                     └────────┬────────┘      │
     │                              │               │
     │                              ▼               │
     │                     ┌─────────────────┐      │
     │                     │  Retrospective   │      │
     │                     │  (what went      │      │
     │                     │   well/badly?)   │      │
     │                     └────────┬────────┘      │
     │                              │               │
     │                 ┌────────────┴────────────┐  │
     │                 │                         │  │
     │                 ▼                         ▼  │
     │        ┌──────────────┐          ┌──────────┐│
     │        │ Update skill │          │ Update   ││
     │        │ knowledge    │          │ person   ││
     │        │              │          │ knowledge││
     │        │ fastapi.yaml │          │ or rules ││
     │        └──────────────┘          └──────────┘│
     │                 │                         │  │
     │                 └────────────┬────────────┘  │
     │                              │               │
     │                              ▼               │
     │                     ┌─────────────────┐      │
     │                     │  Next project    │      │
     │                     │  uses updated    │      │
     │                     │  knowledge       │◀────┘
     │                     └─────────────────┘
     │
     └──────────────────────────────────────────────┘
```

### What exists today (Phase 1)

- ✅ Skills as shared, reusable knowledge units
- ✅ Persons with structured context (identity, skills, knowledge, rules)
- ✅ Prompt composition at runtime from structured parts
- ✅ Skills referenced (not duplicated) across persons
- ✅ YAML files — human-readable, editable, version-controllable

### What's needed next

| Step | What | Status |
|---|---|---|
| **Evaluation** | Structured quality scoring after each task output | Planned |
| **Retrospective** | `python main.py retro <project-id>` — AI reviews what went well/badly | Planned |
| **Auto-update** | Retrospective findings automatically update skills/persons | Planned |
| **Quality tracking** | `python main.py quality` — trends across projects | Planned |

---

## Manual Improvement (Available Now)

Even without automation, you can improve the system today by editing
YAML files directly:

### Add knowledge to a skill

```bash
# Everyone who uses FastAPI learns this
vim company/skills/fastapi.yaml
```

```yaml
knowledge:
  - "Use async def for route handlers"
  - "Use Pydantic models for request/response validation"
  - "NEW: Always use status_code parameter in route decorators"  # ← add this
```

### Add a rule to a person

```bash
# Only backend_coder gets this rule
vim company/persons/backend_coder.yaml
```

```yaml
rules:
  - "Write complete, runnable code"
  - "No placeholders, no TODOs"
  - "NEW: Every function must have error handling for edge cases"  # ← add this
```

### Add a new skill

```bash
# Create a new skill file
vim company/skills/kubernetes.yaml
```

```yaml
id: kubernetes
name: Kubernetes
category: tool
knowledge:
  - "Use Deployments, not bare Pods"
  - "Always set resource limits"
  - "Use ConfigMaps for config, Secrets for credentials"
```

Then reference it from any person's `skills` list.

---

## Why This Design

| Alternative | Problem |
|---|---|
| Monolithic system_prompt | Can't update part of it. Can't share across persons. |
| Prompt patches (append strings) | Grows chaotically. Can't remove or categorize. |
| Database storage | Not inspectable. Can't version-control. Not editable by humans. |
| **Structured YAML layers** | **Right level. Shareable. Inspectable. Editable. Versionable.** |
