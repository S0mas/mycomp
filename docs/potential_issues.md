# Potential Issues & Deferred Improvements

Issues found during the documentation audit that are intentionally **not fixed** — either
because the fix requires a larger architectural decision, or because the benefit/cost
trade-off doesn't justify the change now. Each entry explains the issue, the impact,
and the design notes for when it eventually gets addressed.

---

## Issue 3 — No parallel task execution

**Location**: `aicompany/orchestrator.py` — `run_project()`

**Description**: The topological sort produces a correct dependency ordering, but the
execution loop is strictly sequential. Tasks that have no dependency relationship with each
other are still executed one after another.

**Impact**: For a 6-task project where tasks 2, 3, and 4 are all independent (all depend
only on task 1), they currently run in sequence instead of concurrently. Wall-clock time
grows linearly with the number of independent tasks.

**Why deferred**: Parallel execution requires either:
- `asyncio` rewrites of `run_project`, `_execute_task`, `run_pattern`, and every reasoner
- Or a thread/process pool with thread-safe plan persistence

Both require significant refactoring of the execution model. The current sequential loop
is simple, crash-safe (plan saved after each task), and easy to debug. Parallelism should
be introduced once the serial path is stable and proven.

**Design notes for the fix**:
- Group tasks by "frontier" (all tasks whose deps are satisfied at the same time)
- Execute each frontier group concurrently with `asyncio.gather` or `concurrent.futures`
- Plan persistence must be atomic per-task (already the case — each task saves independently)
- Human checkpoints (`is_checkpoint=True`) must still serialize; skip parallelism for
  checkpoint tasks

---

## Issue 6 — `materialize_files` vs MCP direct writes

**Location**: `aicompany/registry.py` — `materialize_files()`

**Description**: `materialize_files` parses `<write_file path="...">content</write_file>`
XML blocks from agent output text and writes them to the workspace. It is not called by the
orchestrator in normal execution — agents using the Anthropic MCP backend write files
directly via the `write_file` MCP tool instead.

**Impact**: The two file-write mechanisms are not documented relative to each other, which
can cause confusion about which one to use when. The function itself is correct and tested.

**Clarification — when to use each**:

| Mechanism | When to use |
|-----------|-------------|
| MCP `write_file` tool | Normal `run` with `AICOMPANY_MCP_SERVERS` configured. Agents call `write_file` from within their LLM response and the MCP server writes the file directly. |
| `registry.materialize_files` | Non-MCP backends (e.g. OpenAI without MCP, or custom backends). The agent embeds file content in its text output using `<write_file path="...">` XML, and the caller parses + writes them. |

**Why deferred**: No immediate breakage — the function is tested and correct. The fix is
a documentation update to BACKENDS.md explaining the two write paths, and potentially
calling `materialize_files` as a fallback in `_execute_task` when MCP is not configured.

---

## Issue 8 — No agent output validation

**Location**: `aicompany/orchestrator.py` — `_execute_task()`

**Description**: The string returned by `run_pattern()` is saved directly to
`outputs/{task_id}.md` and marked as the task's authoritative output. If an agent returns
an error message, a refusal, or nonsense text, the task is marked `"done"` and the garbage
output propagates as context to all downstream tasks.

**Impact**: A single bad agent response can silently poison the context for all dependent
tasks. The user only sees the problem indirectly — when downstream task outputs are
nonsensical — rather than at the source.

**Why deferred**: Validation would need to be domain-specific per task type. A
"write code" task has different output expectations than a "write tests" task or a "review"
task. Generic heuristics (minimum length, no error keywords) would produce false positives
on legitimate short or error-containing outputs.

**Design notes for the fix**:
- Add a `validate_task_output(task: Task, output: str) -> list[str]` hook in orchestrator
- Each team or task type can register an output validator
- The simplest baseline: reject outputs shorter than `N` chars, or containing known LLM
  refusal patterns ("I cannot", "As an AI")
- On failure: retry `_execute_task` up to once before marking the task failed

---

*These issues are tracked here so they are not forgotten. When addressing them, read the
design notes above and update this file (or remove the entry) when the fix lands.*
