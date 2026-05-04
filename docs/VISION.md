# Vision — AI Company

## The Idea

A solo developer should be able to deliver complex software projects at the speed and quality of a small team. AI makes this possible — but only when it is woven into the entire development process, not just used as an autocomplete tool inside an editor.

**AI Company** is a framework for running an AI-driven software company from a single terminal. You provide a vision and requirements. The system plans the project, assembles the right team of AI agents, executes the work, and delivers outputs — pausing only at decisions that genuinely require human judgement.

---

## Core Principles

**Input → Output, not Input → Babysitting**
The user's job is to define *what* to build and to approve high-stakes decisions. Everything else — planning, team composition, task execution, documentation — should happen without prompting the user for every step.

**The company learns over time**
Every project adds to the company's registry. Teams created for one project become available for the next. Technologies seen accumulate. The company gets smarter and faster with each engagement.

**Human oversight at the right moments**
Full autonomy is not the goal. The goal is autonomy at the *right* level. Deployment to production, payment integrations, security configuration, irreversible changes — these are checkpoints. Everything else runs unattended.

**File-based, inspectable state**
All company state, project plans, task outputs, and decisions are plain YAML and Markdown files. Nothing is hidden in a database. The user can read, edit, and version-control everything. The system is an assistant to the developer, not a black box.

**Minimal by default, extensible by design**
Every layer of the system is designed to be replaced or extended without touching the others. LLM provider, team definitions, tool integrations, storage backend — all are behind clear interfaces.

---

## The SDLC We Want to Cover

The long-term goal is to automate or augment every phase of the software development life cycle:

| Phase | Goal |
|---|---|
| Requirements & Planning | Convert natural-language vision into structured, actionable plans |
| Architecture & Design | Propose tech stacks, patterns, and tradeoffs based on requirements |
| Coding & Implementation | Generate production-quality code via specialist AI agents |
| Testing & QA | Auto-generate tests, measure coverage, flag regressions |
| Code Review & Security | Scan for vulnerabilities, style issues, and logic errors |
| CI/CD & Deployment | Orchestrate builds, tests, and deployments via pipelines |
| Monitoring & Ops | Detect anomalies, summarise incidents, recommend fixes |
| Documentation | Keep docs in sync with code automatically |

---

## What "Teams" Mean

A team is not a group of people. It is an AI agent with:
- A **role** (e.g., Backend Engineer, DevOps Engineer, Security Auditor)
- A **skill set** that determines which tasks it is assigned
- A **system prompt** that defines how it thinks, what it produces, and how it formats output
- An optional **tool list** for future integrations (web search, code execution, file access)

Teams are created on demand. When the CTO's plan requires a skill the company doesn't have, the HR agent designs a new team. That team is saved to the company registry and reused in future projects.

---

## What the User Controls

The user is the **CEO and architect**. Their inputs are:
1. A requirements document (Markdown) at the start of a project
2. Approve / Reject / Modify decisions at checkpoints during execution

Everything else is delegated.

---

## Roadmap

### Phase 1 — Foundation (current)
- CLI: `init`, `new-project`, `run`, `status`
- CTO agent: requirements → structured plan
- HR agent: auto-create missing teams
- Team agents: execute tasks and produce Markdown outputs
- Human checkpoint system: Approve / Reject / Modify
- File-based state: YAML for everything
- Test suite: 83 tests, no API key needed

### Phase 2 — Tool Use
- Give team agents real tools: file read/write, shell execution, web search
- Backend engineer can write code directly to the project filesystem
- DevOps engineer can run Docker builds and check outputs
- Security auditor can run static analysis tools

### Phase 3 — CI/CD Integration
- Auto-generate GitHub Actions workflows for each project
- Run tests in CI on every task output
- Block task completion if tests fail; loop back to the team agent

### Phase 4 — Multi-Project Memory
- Cross-project knowledge base: lessons learned, reusable modules, known pitfalls
- The CTO can reference past projects when planning new ones
- Teams accumulate context_notes from completed engagements

### Phase 5 — Client Interface
- Structured intake: client fills a form → requirements document generated
- Progress dashboard: real-time task status visible to non-technical stakeholders
- Delivery packaging: final outputs bundled with documentation and deployment instructions

### Phase 6 — Self-Improvement
- The company reviews its own outputs and identifies what went wrong
- Prompts and team definitions are updated based on post-project retrospectives
- Over time, the company gets measurably better at specific domains

---

## What This Is Not

- Not a chatbot wrapper. The user does not chat with an AI. They define work and review decisions.
- Not a code editor plugin. This operates at the project level, not the file level.
- Not a replacement for human expertise. The user is still the architect, the decision-maker, and the quality gate.
- Not locked to any LLM. The `llm.py` module is the only place Claude is referenced. Swapping providers is a one-file change.
