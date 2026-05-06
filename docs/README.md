# mycomp Documentation

AI-driven SDLC orchestrator. The developer provides requirements; the system plans, builds
teams, and executes — with human approval at critical checkpoints.

---

## Reading order

| # | Document | Start here if you want to… |
|---|----------|---------------------------|
| [01](01-overview.md) | Overview | Understand what mycomp is in 5 minutes |
| [02](02-architecture.md) | Architecture | See how all modules connect |
| [03](03-data-models.md) | Data models | Understand the data structures |
| [04](04-flow-init.md) | Init flow | Know what `./mycomp init` creates |
| [05](05-flow-new-project.md) | New-project flow | Trace `./mycomp new-project` end-to-end |
| [06](06-flow-run.md) | Run flow | Understand task execution and checkpoints |
| [07](07-llm-layer.md) | LLM layer | Work with backends or add a new provider |
| [08](08-communication.md) | Communication patterns | Understand how agents collaborate |
| [09](09-mcp-server.md) | MCP server | Expose tools to Claude agents |
| [10](10-config.md) | Configuration | All env vars, paths, and thresholds |
| — | [Potential issues](potential_issues.md) | Known deferred issues with design notes |

---

## Existing narrative docs

- [VISION.md](VISION.md) — project philosophy and roadmap
- [ARCHITECTURE.md](ARCHITECTURE.md) — original architecture overview
- [BACKENDS.md](BACKENDS.md) — LLM provider configuration
- [SELF_IMPROVEMENT.md](SELF_IMPROVEMENT.md) — future cross-project learning ideas

---

## Quick start

```bash
./mycomp init                              # bootstrap company state (once)
./mycomp new-project path/to/reqs.md      # plan a project
./mycomp run <project-id>                  # execute tasks (requires MCP server)
./mycomp run --dry-run <project-id>       # preview tasks without LLM calls
./mycomp status [project-id]              # check progress
```
