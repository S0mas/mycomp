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

---

## Issue 1 — Recursive sub-plan teams never created ✅ FIXED

**Location**: `aicompany/planning.py` — `_build_task_tree()`

**Description**: `_create_missing_teams` was only called once in `plan_and_create_project`
using the top-level `teams_required`. When `_build_task_tree` ran the recursive CTO for
a composite task, the sub-plan returned its own `teams_required`, but no code created those
teams. The orchestrator would crash with `FileNotFoundError` at execution time when it tried
to `load_team_with_members` for a team that was never built.

**Fix**: Call `_create_missing_teams` inside `_build_task_tree` immediately after the
`approved_sub_plan` is obtained, using the sub-plan's `teams_required` and `tech_stack`.
Also added `_validate_hr_result` — structural validation of HR output — since recursive
creation makes corrupt HR responses more dangerous (see Issue 7).

---

## Issue 2 — `state_yaml` is stale during recursive planning ✅ FIXED

**Location**: `aicompany/planning.py` — `plan_and_create_project()` → `_build_task_tree()`

**Description**: `state_yaml` was serialized once at the top of `plan_and_create_project` and
passed as a frozen string into every recursive `CTOPlanning().run()` call. Teams HR created for
the top-level plan were invisible to sub-level CTO sessions.

**Fix**: Removed `state_yaml` as a parameter entirely. `CTOPlanning.run()` now calls
`registry.load_state()` at the start of each invocation, so every CTO call — top-level or
recursive — sees the current registry state including teams just created by HR.

---

## Issue 3 — CTO JSON parsing failure has no retry ✅ FIXED

**Location**: `aicompany/planning.py` — `CTOPlanning.run()`

**Description**: The original `CTOPlanning.run()` ended with `return _extract_json_block(cto_output)`,
forcing the CTO to simultaneously reason and format JSON in the same text output. If the final
synthesis didn't contain a clean ` ```json ` block, `_extract_json_block` raised `ValueError`
and crashed the entire `plan_and_create_project` call after expensive requirement validation work.

**Fix**: Separated reasoning from structured output. The CTO now writes human-readable Markdown
during planning (which the Technical Analyst reviews). In the final synthesis, the CTO writes
`cto_plan.json` to the workspace using the Write tool. `CTOPlanning.run()` reads that file after
the pattern completes. If the file is missing, a clear `ValueError` is raised. The file is always
cleaned up after reading (or on error via `missing_ok=True`).

**Benefits**:
- No JSON buried in prose — format failures are eliminated by channel separation
- Analyst reads clean Markdown, not a JSON blob — review quality improves
- Error message is explicit: "CTO did not write cto_plan.json"
- Stale leftover files from prior failed runs are cleaned up before each new run

---

## Issue 4 — Checkpoints absent in sub-task execution ✅ FIXED

**Location**: `aicompany/orchestrator.py` — `_execute_subtask_plan()`

**Description**: `run_project` gates every root-level task marked `is_checkpoint=True` behind
a human A/R/M prompt. `_execute_subtask_plan` had no equivalent guard, so sub-tasks with
`is_checkpoint=True` executed silently without human approval.

**Fix**: Added checkpoint gating inside `_execute_subtask_plan` using the existing
`_handle_checkpoint`. The task's own `Plan` object (already loaded) serves as the
`decisions_log` target. After the checkpoint decision, the task plan is saved to disk
(covering Issue 5 as well). Rejected sub-stubs are marked failed and downstream deps skip.

---

## Issue 5 — Sub-task plan status never persisted to disk ✅ FIXED

**Location**: `aicompany/orchestrator.py` — `_execute_subtask_plan()`

**Description**: `_execute_subtask_plan` updated sub-stub `.status` in memory but never wrote
the task-level `plan.yaml` back to disk. On crash and resume, all sub-stubs showed as `"pending"`.

**Fix**: Added `registry.update_task_plan(project_id, task_plan.id, task_plan)` after every
status change inside `_execute_subtask_plan` — on success, on dependency failure, and on
checkpoint rejection. `registry.update_task_plan` is a new helper that does a BFS search to
find the existing plan file and overwrites it in place, without needing to know the parent
directory path.

---

## Issue 6 — Checkpoint fires with `prior_output=None` ✅ FIXED

**Location**: `aicompany/orchestrator.py` / `aicompany/oversight.py`

**Description**: `oversight.checkpoint()` had a `prior_output: str | None` parameter and dead
code to display it, but it was always passed as `None`. The user never saw meaningful context.

**Fix**: Removed `prior_output` entirely — it was dead code. The checkpoint UI now shows the
task ID, title, and assigned team, followed immediately by the A/R/M prompt. The user can
inspect output files directly if they need prior context before deciding.

---

## Issue 7 — HR-created team data is not structurally validated ✅ FIXED

**Location**: `aicompany/planning.py` — `HRTeamCreation`

**Description**: `HRTeamCreation.run()` was a single LLM call using the same fragile
JSON-in-text approach as CTO (Issue 3). No quality review of identity, knowledge, or rules.

**Fix**: Two-phase approach using file output throughout:
1. **Creation**: HR is instructed to write `hr_team.json` using the Write tool (same pattern
   as CTO/cto_plan.json). The system prompt now includes concrete quality guidance: identities
   must be 2-3 sentences in second person, knowledge items must be specific and actionable,
   rules must start with Always/Never/When. HR raises `ValueError` if the file is not written.
2. **Review**: A second `_sdk_query()` pass (HR Quality Reviewer) receives the proposed team
   JSON, checks it against the quality criteria, and writes `hr_team_review.json` containing
   either `{"verdict": "approved"}` (keep proposed) or the corrected team dict (use instead).

Both files are cleaned up after reading. A `_sdk_query` helper centralises the SDK boilerplate.
`_validate_hr_result` still runs after the review as a final structural guard.

---

## Issue 8 — Deduplication merge plan not validated before application ✅ FIXED

**Location**: `aicompany/planning.py` — `_apply_dedup_merges()`

**Description**: `_apply_dedup_merges` trusted the AI's merge plan completely. Hallucinated
or swapped IDs would corrupt the plan tree with no rollback.

**Fix**: Added `_validate_dedup_merges(merges, proj_root, on_status)` that runs before
`_apply_dedup_merges`. It uses `_collect_known_task_ids` (reads all plan.yaml files via our
Python API) to enumerate the real task IDs on disk, then filters each merge group:
- `keep` ID must exist in the tree
- all `remove` IDs must exist in the tree
- no `remove` ID may be a `keep` in another group (cascading invalidation)
- `keep` may not appear in its own `remove` list

Invalid groups are skipped with an `on_status` warning. `_apply_dedup_merges` is only called
if at least one valid group remains.

---

## Issue 9 — `_scope_requirements` silently produces empty requirement lists ✅ FIXED

**Location**: `aicompany/planning.py` — `_build_task_tree()`

**Description**: `_scope_requirements` returned `[]` silently when `requirement_ids` didn't
match any parent requirement. Tasks executed with zero requirements context.

**Fix**: Two `on_status` warnings added inside `_build_task_tree`:
1. **Dangling ref**: if a leaf task provides non-empty `requirement_ids` but `_scope_requirements`
   returns nothing, warn with the specific IDs that didn't match.
2. **Coverage gap**: after the full sibling set is built, compute which parent requirement IDs
   were never claimed by any leaf task and warn with the uncovered IDs.

Both are warnings (not errors) — planning continues. The coverage tracking uses the scoped
results already computed in the loop (no extra disk reads).

---

## Issue 10 — Leaf task context is too thin for teams with dependencies

**Location**: `aicompany/orchestrator.py` — `_build_project_context()`

**Description**: The context built for each team includes task title, raw dependency IDs (not
titles), workspace path, and scoped requirements. The project title and tech stack are absent.
Dependency IDs tell teams nothing about what those tasks produced or where to find their
outputs.

**Impact**: Teams with dependencies must explore the workspace blindly. Every agent spends
early turns on discovery that structured context could provide in advance.

**Design notes for the fix**:
- Include project title and tech stack (load from root plan or task plan).
- Load stub titles for each dependency ID and include them: "Depends on: task_001 (Design
  schema), task_002 (Implement auth middleware)" instead of "Depends on: task_001, task_002".
- Optionally include the workspace relative paths of dependency outputs when they exist.

---

## Issue 11 — Composite task output is an unstructured blob

**Location**: `aicompany/orchestrator.py` — `_execute_subtask_plan()`

**Description**: Sub-task outputs are joined with `"\n\n---\n\n"` and saved as the composite
task's output file. There's no attribution (which sub-output came from which team), no
summary, no structure. A downstream task that reads this output file gets an unlabelled wall
of text.

**Design notes for the fix**:
- Add per-sub-task headers before joining: `f"## {sub_stub.title} ({sub_stub.assigned_team})\n\n{sub_output}"`.
- Or generate a short synthesis summary at the end of `_execute_subtask_plan` using the
  lead_delegates pattern with a "Project Lead" persona that summarises what was built.

---

## Issue 12 — Cross-level `depended_on_by` is inconsistent

**Location**: `aicompany/planning.py` — `_build_task_tree()`, `_apply_dedup_merges()`

**Description**: `depended_on_by` is computed locally within each `_build_task_tree` call,
only across siblings at the same tree level. After deduplication, `_apply_dedup_merges`
recomputes `depended_on_by` per `plan.yaml` file — again, only within each file's own task
list. Cross-plan-file reverse edges are never tracked.

**Impact**: The "Required by" field shown to teams in task context (`_build_project_context`)
may be incomplete. Deduplication decisions that create cross-level dependencies leave
`depended_on_by` permanently stale.

**Design notes for the fix**:
- After full tree assembly, run a single BFS traversal that builds a global `{task_id: [task_id]}`
  reverse map, then writes `depended_on_by` into each `plan.yaml` stub in one pass.
- This global pass should also run after deduplication.

---

## Issue 13 — Dedup agents run unrestricted in the project directory

**Location**: `aicompany/planning.py` — `Deduplication.run()`

**Description**: Dedup `PersonAgent` instances use `permission_mode="bypassPermissions"` and
`workspace=proj_root`. They can freely write files anywhere under `proj_root`, including
`plan.yaml` files. A malfunctioning dedup agent could write directly to plan files, bypassing
the controlled `_apply_dedup_merges` function.

**Impact**: Direct writes to plan files by agents would produce undetectable corruption — the
YAML may be syntactically valid but semantically broken (wrong IDs, missing fields, duplicate
tasks).

**Design notes for the fix**:
- Have dedup agents write their merge plan to a dedicated file (e.g. `dedup_plan.json`) in
  the project root, then `_apply_dedup_merges` reads that file rather than trusting the
  pattern output string. This doesn't prevent direct writes but makes the intended channel
  explicit and auditable.
- Long-term: a read-only permission mode in the SDK would be the correct fix, but that
  requires upstream changes.

---

*These issues are tracked here so they are not forgotten. When addressing them, read the
design notes above and update this file (or remove the entry) when the fix lands.*
