# F-11: Unified Dependency Checks at Task Start

**Date:** 2026-04-19
**Feature:** F-11 Feature Dependency Enforcement (Epic: Board / Workflow)
**Scope:** T-223 (spec), T-226 (plan), T-36 (feature-level impl), T-224 (task-level impl), T-225 (dogfood F-48 ordering)

## Problem

Today cloglog has **two ways a task can be blocked** from starting, but only one of them is enforced at `start_task`:

1. **Feature-level**: a task's parent feature declares upstream features via `feature_dependencies`. If any upstream feature still has incomplete tasks, the downstream task shouldn't start. The table, repository methods, routes (`POST /features/{id}/dependencies`), and MCP tool (`add_dependency`) all exist — but **`start_task` ignores them**. That gap is T-36.
2. **Task-level**: "task X must finish before task Y" within the same feature (or across features in the same project). There is no data model, no API, no guard. Everything is prose in task descriptions. F-48's lifecycle work (T-213…T-222) is the canonical example — the ordering lives only in human-readable notes.

This spec designs the complete `start_task` dependency behaviour — feature-level and task-level together — so both layers land coherently, share an error shape, and leave room for UI in a follow-up.

## Design Decisions

| # | Decision | Choice | Rationale |
|---|---|---|---|
| 1 | Task-dep storage | New `task_dependencies` table (`task_id`, `depends_on_task_id`, composite PK) | Mirrors `feature_dependencies`; cycle detection and graph queries stay uniform; avoids JSON column anti-pattern that would need denormalised indexes for lookups |
| 2 | Scope of task deps | Same-project, across-feature allowed; same-feature allowed | Matches feature deps; F-48 has cross-feature orderings implicit in its prose |
| 3 | Guard evaluation | Collect **all** blockers, then 409 | Agent gets the full picture in one round-trip — matters when two blockers resolve independently and the agent plans which to wait on |
| 4 | Guard order inside a 409 | feature → task → pipeline, stable order in the payload | Stable ordering means tests can assert on the payload; humans see the "why can't I start" hierarchy from broad to narrow |
| 5 | Error payload | Structured `detail` object with `code`, `message`, `blockers[]`. `kind` values are `feature` / `task` / `pipeline` | Unifies three previously-string errors into one machine-parseable shape; short `kind` values match the glossary ("a blocker of kind=feature") |
| 6 | `update_task_status` guard | Apply the same check on any transition **into** `in_progress` | Otherwise a status bypass defeats the guard. Transitions to `review`/`backlog`/`done` are unaffected |
| 7 | `create_task` shape | **No change this round** — task deps are added via separate `add_task_dependency` calls | Keep T-224 scope small; a future nicety can accept `blocked_by: UUID[]` on create, but it's a convenience, not a correctness requirement |
| 8 | Cycle detection | DFS, same algorithm as `BoardService.has_cycle` for features | Already battle-tested; identical semantics keep one mental model |
| 9 | Asymmetric "resolved" rule | Task-level `blocked_by` resolves on `done \|\| (review && pr_url)`. Pipeline spec/plan predecessors **also** require `artifact_path`. | Pipeline predecessors gate downstream work that *consumes* the artifact (plan reads spec; impl reads plan). Arbitrary `blocked_by` is just ordering — once the task is merged, downstream can proceed. Different purpose, different rule |
| 10 | Context boundary | **"Is-blocker-resolved" is Board domain.** Expose via a new read-shaped port `BoardBlockerQueryPort.get_unresolved_blockers(task_id) -> list[BlockerDTO]` in `src/board/interfaces.py`, implemented in `BoardService`. Agent guard calls the port and translates to 409. | Prevents the resolution predicate from drifting between Agent and Board if we later add states like "blocked" or "cancelled." Keeps the Conformist surface narrow: Agent reads **one** domain answer ("what's blocking?"), doesn't walk relationships itself. Pipeline check stays in Agent (genuinely Agent-domain — about task-type workflow) |
| 11 | UI treatment | **Out of scope for this spec.** Note as follow-up | Board-card styling can ship separately without blocking the backend guard; T-36/T-224 land the enforcement, UI is a separate F-item |

## Ubiquitous Language

- **Blocker**: anything that prevents a task from entering `in_progress`. A blocker is always typed by `kind` — one of `feature`, `task`, or `pipeline`.
- **blocked_by**: the task-level relation — "task X is blocked_by task Y" means Y must be resolved before X starts. Snake_case everywhere in Python and SQL; camelCase (`blockedBy`) only in TypeScript/MCP payloads where that's the local convention.
- **Resolved**:
  - A **task** blocker is resolved when the upstream task has `status == 'done'` OR (`status == 'review' AND pr_url IS NOT NULL`). **No artifact check** — task-level `blocked_by` is about task completion, not artifact attachment. This is deliberately asymmetric from the pipeline rule (see Decision #9).
  - A **feature** blocker is resolved when every task in the upstream feature is resolved by the same task-level rule.
  - A **pipeline** blocker is resolved per the existing `_check_pipeline_predecessors` rule, which **does** enforce artifact attachment for spec/plan predecessors.
- **Dependency graph (task-level)**: directed acyclic graph over tasks within one project.

## Data Model

### New table: `task_dependencies`

```sql
CREATE TABLE task_dependencies (
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    depends_on_task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    PRIMARY KEY (task_id, depends_on_task_id),
    CHECK (task_id <> depends_on_task_id)
);

CREATE INDEX ix_task_dependencies_depends_on_task_id
    ON task_dependencies (depends_on_task_id);
```

Semantics: `(task_id=X, depends_on_task_id=Y)` means "X is blockedBy Y". Same orientation as `feature_dependencies`.

**Migration**: new Alembic revision. `down_revision` must point at the **actual latest head on `main` at push time**, not at the ID recorded here. At the moment this spec was written, `python -m alembic history` in the worktree shows `f5a6b7c8d9e2_add_task_artifact_path` as head; by the time T-224 pushes, a different context may have landed a migration in front, so the impl plan explicitly calls out re-reading `alembic history` before committing. `ON DELETE CASCADE` so deleting a task cleans up its edges both ways.

### ORM

In `src/board/models.py`, add to `Task`:

```python
dependencies: Mapped[list["Task"]] = relationship(
    secondary="task_dependencies",
    primaryjoin="Task.id == task_dependencies.c.task_id",
    secondaryjoin="Task.id == task_dependencies.c.depends_on_task_id",
    lazy="selectin",
)
dependents: Mapped[list["Task"]] = relationship(
    secondary="task_dependencies",
    primaryjoin="Task.id == task_dependencies.c.depends_on_task_id",
    secondaryjoin="Task.id == task_dependencies.c.task_id",
    lazy="selectin",
    viewonly=True,
)
```

### Repository methods (additions in `src/board/repository.py`)

```python
async def add_task_dependency(self, task_id: UUID, depends_on_task_id: UUID) -> None
async def remove_task_dependency(self, task_id: UUID, depends_on_task_id: UUID) -> bool
async def get_task_dependency_exists(self, task_id: UUID, depends_on_task_id: UUID) -> bool
async def get_task_dependencies(self, task_id: UUID) -> list[UUID]
async def get_all_task_dependencies(self, project_id: UUID) -> list[tuple[UUID, UUID]]
```

### Service methods (additions in `src/board/services.py`)

```python
async def has_task_cycle(self, task_id: UUID, depends_on_task_id: UUID) -> bool  # DFS mirror of has_cycle
async def add_task_dependency(self, task_id: UUID, depends_on_task_id: UUID) -> None
async def remove_task_dependency(self, task_id: UUID, depends_on_task_id: UUID) -> bool
```

`add_task_dependency` validates (in order):
1. `task_id != depends_on_task_id` → `ValueError("A task cannot depend on itself")`
2. Both tasks exist → `ValueError("Task not found")`
3. Both tasks belong to the **same project** (walk task→feature→epic→project) → `ValueError("Tasks must be in the same project")`
4. Edge doesn't already exist → `ValueError("DUPLICATE")`
5. No cycle → `ValueError("Adding this dependency would create a cycle")`

## API

### New routes in `src/board/routes.py`

```
POST   /api/v1/tasks/{task_id}/dependencies
       body: { "depends_on_id": "<uuid>" }
       201 → { "status": "created" }
       400 → { "detail": "<validation message>" }
       404 → { "detail": "Task not found" }
       409 → { "detail": "Dependency already exists" }

DELETE /api/v1/tasks/{task_id}/dependencies/{depends_on_id}
       204 → no body
       404 → { "detail": "Dependency not found" } or "Task not found"
```

**Auth** (per `src/gateway/app.py::ApiAccessControlMiddleware`, which gates every `/api/v1/*` route):

- The **middleware** decides which credential shapes are allowed through to any given path:
  - **MCP shape**: `Authorization: <anything>` + `X-MCP-Request: true` → passes the middleware for every path. The middleware does **not** validate the Bearer value here; that's the route's job via a handler-level dependency.
  - **Bearer-only**: only allowed on `/api/v1/agents/*` paths (project API key or agent token).
  - **Dashboard**: `X-Dashboard-Key` → allowed on non-agent paths.
- **Pre-existing gap on `POST /features/{id}/dependencies` / `DELETE .../dependencies/{depends_on_id}`**: the handlers have no route-level auth dependency, so a caller sending `Authorization: Bearer garbage` + `X-MCP-Request: true` slips past the middleware's presence-check and reaches the handler unauthenticated. We **do not retrofit** this in the same PR that adds task-dep routes — existing feature-dep tests use the dashboard-key `client` fixture, and changing the auth shape on a merged route needs its own focused PR. Flagged as a follow-up.
- **New task-dep routes** use a new hybrid dependency `CurrentMcpOrDashboard` (added to `src/gateway/auth.py` by T-36, consumed by T-224). The dep accepts either:
  - a valid MCP service key (**properly validated** — closes the gap on the new surface), or
  - a valid dashboard key (`X-Dashboard-Key` matching `settings.dashboard_key`).

  This matches the middleware's implicit intent (MCP OR dashboard) but enforces the MCP service key at the handler level. New task-dep tests can keep using the shared dashboard-key client fixture (like feature-dep tests) — the hybrid dep accepts that path. The MCP server's calls continue to work since they already send `Authorization: Bearer <mcp_service_key>` + `X-MCP-Request: true`.
- Project API keys and agent tokens are rejected (middleware returns 403 before the handler runs). Agents never call these endpoints directly; they go through MCP.

**Events**: reuse the existing `EventType.DEPENDENCY_ADDED` / `DEPENDENCY_REMOVED` enum values (do **not** introduce `TASK_DEPENDENCY_*` new names — the frontend's `useDependencyGraph` hook and `useSSE` typed union only listen for the existing names; new names would be silently ignored, leaving the dep graph stale until manual refresh). Add a `scope: "feature" | "task"` discriminator to the event `data` payload so future UI work can distinguish:

```python
# feature dep (existing — add scope field, backwards-compat: extra field ignored by current consumer)
data={"scope": "feature", "feature_id": ..., "depends_on_id": ...}

# task dep (new)
data={"scope": "task", "task_id": ..., "depends_on_id": ...}
```

Today's frontend refetches the whole graph on these events unconditionally, so the task-dep case works immediately without frontend changes. When the dashboard grows task-dep visualisation, it can switch on `scope`.

## MCP tools

Added in `mcp-server/src/tools.ts` and registered in `server.ts`:

- `add_task_dependency({ task_id, depends_on_id })` → `POST /api/v1/tasks/{task_id}/dependencies`
- `remove_task_dependency({ task_id, depends_on_id })` → `DELETE /api/v1/tasks/{task_id}/dependencies/{depends_on_id}`

Naming convention: the feature-level tools are called `add_dependency` / `remove_dependency` (historical — they predate the idea of task deps). The new tools carry the `task_` prefix to disambiguate, and the feature tools keep their names (backwards compat — nothing renames).

**Follow-up (not in this wave)**: publish `add_feature_dependency` / `remove_feature_dependency` as symmetric aliases for the existing tools, then mark the unprefixed names deprecated. Restores naming symmetry without a breaking rename.

## Guard semantics

### Port split between contexts

- **Board owns** the "is this blocker resolved?" semantics for feature and task blockers (data + rule). Exposed via a new port:

  ```python
  # src/board/interfaces.py
  class BoardBlockerQueryPort(Protocol):
      async def get_unresolved_blockers(self, task_id: UUID) -> list[BlockerDTO]: ...
  ```

  `BlockerDTO` is a pure data record (TypedDict/dataclass) with fields matching the payload shape below — no SQLAlchemy models cross the boundary.

- **Agent owns** the **pipeline** rule (task-type workflow: spec→plan→impl). `_check_pipeline_predecessors` stays where it is. It emits pipeline blockers that Agent splices in with the Board-provided list.

### Wiring (port injection)

Today `AgentService.__init__` takes `repo: AgentRepository, board_repo: BoardRepository`. The new guard needs a `BoardBlockerQueryPort` implementation — concretely `BoardService`, since it owns the resolution logic. Two constructor-shape options for the plan to choose from:

1. **Additive**: add `board_blockers: BoardBlockerQueryPort` as a new constructor argument. Keep `board_repo` (still used elsewhere in `AgentService` for `get_task`, `get_tasks_for_feature`, `update_task`). Route composition in `src/agent/routes.py` instantiates `BoardService(BoardRepository(session))` once and passes it. Preferred — smallest delta, explicit dependency.
2. **Replacement**: replace `board_repo` with a richer Board-facing port covering everything Agent needs (reads + writes for status). Bigger refactor, deferred.

Plan should default to option 1. Both `src/agent/routes.py` (the route-composition site) and every `AgentService(...)` construction in tests/conftest need to pass the new port. Grep for `AgentService(` to find constructions.

### `start_task` — new behaviour

Order of checks, stable, collecting all blockers:

1. Worktree exists (404 on miss — unchanged).
2. Task exists (404 on miss — unchanged).
3. Single-active-task guard (unchanged; still raises immediately — this is about agent state, not task state).
4. **Blocker collection pass** (new):
   - Call `board_blocker_query.get_unresolved_blockers(task_id)` → returns feature and task blockers in stable order.
   - Run pipeline check (reworked from `_check_pipeline_predecessors`) → returns pipeline blockers instead of raising.
   - Concatenate: `[feature…, task…, pipeline…]`.
5. If list non-empty, raise structured 409 (see below).
6. Otherwise assign worktree + set `in_progress` + publish event (unchanged).

### `update_task_status` — new behaviour

When the new status is `in_progress` (regardless of previous status), run the same blocker collection pass as `start_task` step 4. Any other target status (`review`, `backlog`, `done`) is unaffected.

Rationale: Today, an agent that hit a blocker on `start_task` could theoretically work around it by calling `update_task_status(status="in_progress")` directly. Mirroring the check closes the hole.

### Guard composition (same-agent vs. cross-agent chains)

The single-active-task guard (step 3) and the blocker-collection pass (step 4) **compose** — they are not alternatives. That composition changes the effective "ready to start" criterion depending on whether the dependent task is picked up by the **same** worktree that shipped the blocker or a **different** one:

- **Cross-worktree** (the usual case — dogfood scenario for T-225): worktree A ships T-1 (merges PR or leaves it in `review` with `pr_url`), worktree B picks up T-2 where `T-2 blocked_by T-1`. On B's `start_task(T-2)`, step 3 (single-active-task) only inspects B's own tasks, so T-1 is invisible to it. Step 4 consults Board's resolver, which accepts `done || (review && pr_url)`. Result: B can start T-2 the moment T-1 is in `review` with a PR URL — no need to wait for the user to drag T-1 to `done`.
- **Same-worktree chain**: worktree A holds T-1 and then wants to start T-2 against the same worktree. Step 3 rejects whenever T-1 is in `in_progress` or (`review` with `pr_merged == False`). So the effective threshold for same-worktree chains is stricter than the blocker-resolver alone: **T-1 must be `done`, OR `review` with `pr_merged=True`**. This is intentional — one active task per agent is an independent invariant — but spec readers and impl/test authors must not mistake the blocker-resolver's rule for the full set of preconditions.

Test expectations must reflect both shapes: the cross-agent tests assert happy-path on `review + pr_url`; the same-agent tests assert 409 from the active-task guard (not the blocker guard) on that same state. The error payload in the two cases is different: cross-agent hits the new structured `task_blocked` response; same-agent hits the pre-existing `Cannot start task: agent already has active task(s)…` string (unchanged by this spec).

## Error payload shape

Unified for all three blocker kinds. `FastAPI.HTTPException` accepts a dict `detail`, which serialises as JSON.

```json
{
  "detail": {
    "code": "task_blocked",
    "message": "Cannot start task T-225: 1 blocker(s) not resolved.",
    "blockers": [
      {
        "kind": "feature",
        "feature_id": "…",
        "feature_number": 48,
        "feature_title": "Agent Lifecycle Hardening",
        "incomplete_task_numbers": [213, 214, 215, 217, 219, 220]
      },
      {
        "kind": "task",
        "task_id": "…",
        "task_number": 222,
        "task_title": "Canonical lifecycle doc",
        "status": "in_progress"
      },
      {
        "kind": "pipeline",
        "predecessor_task_type": "plan",
        "task_id": "…",
        "task_number": 226,
        "task_title": "Plan: implementation plan",
        "status": "review",
        "reason": "artifact_missing"
      }
    ]
  }
}
```

`reason` on a `pipeline` blocker is `"artifact_missing"` or `"not_done"`.

- HTTP status: **409 Conflict** for any guard violation (matches current pipeline predecessor code).
- `code: "task_blocked"` is the stable machine-readable discriminator the MCP layer and UI can switch on.
- `blockers` is always an array even with one entry; order is the guard order above (feature → task → pipeline).

**Client wiring requirements** (discovered during review):

- `mcp-server/src/client.ts`'s current `request()` implementation discards the JSON body on non-2xx (`throw new Error(\`cloglog API error: ${response.status} ${text}\`)`). A structured `detail` object becomes unparseable raw text. T-224 updates `request()` to:
  1. Read `Content-Type` and, if `application/json`, `JSON.parse(text)` into a `detail` object.
  2. Throw a richer error (custom `CloglogApiError extends Error` with `status`, `code`, `detail` fields) so tool handlers can switch on `code === "task_blocked"` and format the `blockers` array into readable tool output.
- `mcp-server/src/server.ts`'s `start_task` / `update_task_status` tool handlers: catch the new error type, render blockers as a human-readable list in the `isError` tool response so agents see "Cannot start T-225: blocked by T-222 (in_progress), T-36 (not done)…" instead of a JSON blob.
- Dashboard's `frontend/src/api/client.ts` strips 4xx bodies the same way. No UI consumer exists yet for the structured error (agents are the consumer), so the frontend change is **out of scope** for this wave and moves to follow-ups. If a future UI surfaces blocked tasks, its PR also teaches `client.ts` to preserve the body.

**Backwards-compat for pipeline-only cases**: T-36 hasn't shipped yet, T-224 hasn't shipped yet, and the current production 409 is a plain string. Moving to the structured payload is a one-time change that both impl tasks share. Tests today assert on `"Cannot start"` substrings in the string — they'll be updated in lock-step.

## `create_task` / `blocked_by`

Explicitly out of scope for this spec round. Adding a `blocked_by: UUID[]` argument to `mcp__cloglog__create_task` is a convenience we can layer later. Until then, workflow is:

```
create_task(...) → returns task_id
add_task_dependency(task_id, depends_on_id=<blocker_id>)   # repeat per blocker
```

## Interaction with the PR/merge lifecycle

No change to `mark_pr_merged` semantics. A blocker task being in `review` with `pr_url` counts as resolved today and continues to count as resolved. When the user drags to `done`, the blocker transitions from "resolved-with-PR" to "resolved-done" — monotone, no flip-back.

## Follow-ups (out of scope this wave)

- **UI**: render blocked tasks greyed out on the board; tooltip listing blockers; badge with blocker count. Belongs in a new F-item against the frontend.
- **`create_task(blocked_by=[...])`** ergonomic shortcut.
- **Transitive blocker surfacing**: when only the transitive blocker is actionable, could the payload include "this task's blocker is itself blocked by X" chains? Only add when we see agents asking for it.
- **Auto-resume**: when the last blocker resolves, event bus could nudge the waiting agent. Today agents poll via inbox; out of scope.

## Testing strategy

Integration tests only, real DB (per project policy).

Covered:
- **Repository**: add, remove, duplicate, self-loop rejection, cycle rejection, cross-project rejection.
- **Routes** (task-dep): happy-path POST/DELETE, 404 on unknown task, 400 on validation, 409 on duplicate.
- **`start_task` guard — cross-worktree** (covers both T-36 and T-224, upstream blocker lives on a different worktree):
  - Feature blocker: upstream feature with incomplete task → 409 with `kind=feature` entry.
  - Task blocker: `blocked_by` task in `backlog` → 409 with `kind=task` entry.
  - Pipeline blocker: spec in `review` without artifact → 409 with `kind=pipeline` entry + `reason=artifact_missing`.
  - Combined: all three simultaneously → 409 with three entries in stable order (feature → task → pipeline).
  - Happy (resolved-with-PR): upstream task in `review` with `pr_url` → no blocker entry; start succeeds.
  - Happy (resolved-done): upstream task `done` → start succeeds.
- **`start_task` guard — same-worktree chain** (separate tests — the pre-existing active-task guard fires before the new blocker guard):
  - T-1 in `review` with `pr_url` but `pr_merged=False` on worktree W; `start_task(T-2)` on same W → 409 with active-task message (existing, unchanged). Asserts that the blocker guard does **not** mask or replace the active-task guard.
  - Same setup but T-1 has `pr_merged=True` → start succeeds (both guards pass).
- **`BoardBlockerQueryPort`** (Board context): direct unit/integration tests on `get_unresolved_blockers` covering the feature+task matrix (Agent owns the pipeline case, tested separately).
- **`update_task_status`** — same blocker coverage when target status is `in_progress`; transitions to other statuses unaffected.
- **MCP tools**: end-to-end smoke via the test client — `add_task_dependency` round-trips through routes.

## References

- `src/board/routes.py` lines 699–748 — existing feature-dep routes (shape template).
- `src/board/services.py` lines 146–211 — existing feature-dep service methods and cycle detection.
- `src/agent/services.py` lines 157–252 — current `start_task` with pipeline predecessor check.
- `src/agent/services.py` lines 330–398 — current `update_task_status`.
- `docs/superpowers/specs/2026-04-06-reconciliation-loop-design.md` — style reference.
- CLAUDE.md §"Cross-Context Integration" — migration `down_revision` discipline.
