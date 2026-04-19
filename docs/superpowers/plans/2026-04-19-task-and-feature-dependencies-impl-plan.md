# F-11: Unified Task + Feature Dependency Checks — Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the `start_task` dependency guard in two PRs — T-36 (feature-level; foundation) then T-224 (task-level; additive). Both PRs converge on the same port-based design described in the spec.

**Spec:** [`docs/superpowers/specs/2026-04-19-task-and-feature-dependencies.md`](../specs/2026-04-19-task-and-feature-dependencies.md)

**Architecture:**
- `BoardBlockerQueryPort` in `src/board/interfaces.py` owns blocker-resolution semantics. Implemented by `BoardService`.
- `AgentService` gets the port via constructor injection; its guard code collects blockers (Board port) + pipeline entries (`_check_pipeline_predecessors`, reworked to return instead of raise) and raises a single structured 409.
- T-36 lands the port with **only** feature-level blocker implementation; T-224 extends the port to also emit task-level blockers and introduces the `task_dependencies` table, routes, and MCP tools.

**Tech stack:** Python 3.12 / FastAPI / SQLAlchemy 2 / Alembic / Pydantic v2 (backend). Node / TypeScript / @modelcontextprotocol/sdk (MCP server). Pytest integration tests with real Postgres (no mocks).

**PR split rationale:**
- T-36 is a `task_type=task` (no pipeline predecessor). It lands the port, the structured 409 payload, the guard refactor, and the MCP client error-parsing update. Small blast radius — shipping it first derisks the bigger T-224 change.
- T-224 is `task_type=impl`; it assumes the guard plumbing from T-36 is in place and only has to add task-level data (table, repo, routes, MCP tools) and extend `BoardService.get_unresolved_blockers` to include task blockers.

**Shared setup:** Both PRs run `make quality` before every commit (enforced by hook). Both must rebase on `main` and check `python -m alembic history` at push time (T-224 because it writes a migration; T-36 because its guard tests hit the DB schema and need the latest).

**Test strategy:** Integration tests only — real Postgres via `conftest.py`'s session fixture. No mocking of Board internals from Agent tests; use the actual `BoardService`. Same-worktree vs. cross-worktree guard composition is tested against the real `AgentService`.

---

## PR A — T-36: Feature-level guard at start_task

Scope: thread the port, land the structured 409, enforce feature-level blockers. No task-level data model yet. Net change: ~300 LOC Python + ~50 LOC TS (client error type).

### Task A1: Introduce `BoardBlockerQueryPort` with feature-only implementation

**Files:**
- Create: `src/board/interfaces.py` (new file if absent, or extend)
- Modify: `src/board/services.py` (add `get_unresolved_blockers`)
- Create: `tests/board/test_blocker_query.py`

- [ ] **Step 1: Verify baseline**

```bash
cd /home/sachin/code/cloglog/.claude/worktrees/wt-task-deps
uv run pytest tests/board/ -v --tb=short
git log --oneline -3 main..HEAD
```

- [ ] **Step 2: Define the port and DTO**

In `src/board/interfaces.py`, add:

```python
from typing import Protocol, TypedDict, Literal
from uuid import UUID


class FeatureBlocker(TypedDict):
    kind: Literal["feature"]
    feature_id: str
    feature_number: int
    feature_title: str
    incomplete_task_numbers: list[int]


class TaskBlocker(TypedDict):
    kind: Literal["task"]
    task_id: str
    task_number: int
    task_title: str
    status: str


BlockerDTO = FeatureBlocker | TaskBlocker


class BoardBlockerQueryPort(Protocol):
    async def get_unresolved_blockers(self, task_id: UUID) -> list[BlockerDTO]: ...
```

- [ ] **Step 3: Implement feature-blocker resolution on `BoardService`**

In `src/board/services.py`, add:

```python
async def get_unresolved_blockers(self, task_id: UUID) -> list[BlockerDTO]:
    """Return feature + task blockers for `task_id`, in stable order.

    T-36 scope: feature-level only. T-224 extends this to also emit task blockers.
    """
    task = await self._repo.get_task(task_id)
    if task is None:
        return []
    feature = await self._repo.get_feature(task.feature_id)
    if feature is None:
        return []

    blockers: list[BlockerDTO] = []
    dep_feature_ids = await self._repo.get_feature_dependencies(feature.id)
    for dep_fid in sorted(dep_feature_ids):
        dep_feature = await self._repo.get_feature(dep_fid)
        if dep_feature is None:
            continue
        dep_tasks = await self._repo.get_tasks_for_feature(dep_fid)
        incomplete = [t for t in dep_tasks if not _task_resolved(t)]
        if incomplete:
            blockers.append(FeatureBlocker(
                kind="feature",
                feature_id=str(dep_feature.id),
                feature_number=dep_feature.number,
                feature_title=dep_feature.title,
                incomplete_task_numbers=sorted(t.number for t in incomplete),
            ))
    return blockers


def _task_resolved(t: Task) -> bool:
    """Same rule the spec describes for task-level blockers (no artifact check)."""
    if t.status == "done":
        return True
    if t.status == "review" and bool(t.pr_url):
        return True
    return False
```

Module-private `_task_resolved` helper at the bottom of `services.py`.

- [ ] **Step 4: Write integration tests for the port**

Create `tests/board/test_blocker_query.py` covering:

1. Task in a feature with no upstream deps → `[]`.
2. Feature has upstream F-B with all tasks `done` → `[]`.
3. Feature has upstream F-B with one task `backlog` → single entry with `incomplete_task_numbers=[N]`.
4. Feature has upstream F-B with one task `review`+`pr_url` → resolved, `[]`.
5. Feature has upstream F-B with one task `review`+no `pr_url` → entry emitted (unresolved).
6. Multiple upstream features → stable order by feature number.

Use the existing dashboard-auth fixtures from `tests/board/conftest.py`; no new fixtures needed.

- [ ] **Step 5: Verify + stage**

```bash
uv run pytest tests/board/test_blocker_query.py -v --tb=short
uv run ruff check src/board/services.py src/board/interfaces.py
uv run mypy src/board/services.py src/board/interfaces.py
```

### Task A2: Thread the port into `AgentService` and refactor the guard

**Files (all must be updated — don't skip any, a missing one is a runtime `TypeError`):**
- Modify: `src/agent/services.py` (constructor; `_check_pipeline_predecessors`; `start_task`; `update_task_status`)
- Modify: `src/agent/routes.py:39` (the `ServiceDep` factory that backs `start_task` / `update_task_status` / etc.)
- Modify: `src/agent/scheduler.py:27` (scheduled heartbeat/orphan sweep — constructs `AgentService` in a background task; if skipped, the scheduler crashes on the next tick)
- Modify: `src/board/routes.py:98` (`delete_project` handler constructs `AgentService` to clean up agents)
- Modify: `src/board/routes.py:811` (`remove_offline_agents` handler)
- Modify: `tests/agent/test_unit.py` (~30 construction sites — all need updating)
- Modify: `tests/agent/test_integration.py` (3 sites)
- Modify: `tests/e2e/test_heartbeat_timeout.py` (4 sites)
- Any new `AgentService(...)` added by PR B (none planned, but grep again before final push).

- [ ] **Step 1: Grep construction sites**

```bash
grep -rn "AgentService(" src/ tests/
```

Expect the list above. Every site gets an extra positional or keyword argument. Recommendation: use a helper in `tests/agent/conftest.py` (e.g. `make_agent_service(session)`) so new callers don't have to remember — and one-shot edit all existing test sites to use the helper instead of raw `AgentService(...)`. Prod call sites can be updated inline since there are only four and each already composes `BoardRepository(session)` nearby (just add `BoardService(board_repo)` alongside).

- [ ] **Step 2: Update constructor**

```python
# src/agent/services.py
from src.board.interfaces import BoardBlockerQueryPort, BlockerDTO

class AgentService:
    def __init__(
        self,
        repo: AgentRepository,
        board_repo: BoardRepository,
        board_blockers: BoardBlockerQueryPort,
    ) -> None:
        self._repo = repo
        self._board_repo = board_repo
        self._board_blockers = board_blockers
```

- [ ] **Step 3: Refactor `_check_pipeline_predecessors` to return a list**

Rename to `_collect_pipeline_blockers(task, feature_tasks) -> list[BlockerDTO]`. Raise nothing; return `[]` for no blockers, list of `kind="pipeline"` entries otherwise. Move the `PipelineBlocker` TypedDict into `src/agent/interfaces.py` (Agent owns the pipeline rule, not Board).

```python
# src/agent/interfaces.py
class PipelineBlocker(TypedDict):
    kind: Literal["pipeline"]
    predecessor_task_type: str
    task_id: str
    task_number: int
    task_title: str
    status: str
    reason: Literal["artifact_missing", "not_done"]
```

Import it into `AgentService` and use the same list the Board port returns (`list[BlockerDTO]` is now `FeatureBlocker | TaskBlocker | PipelineBlocker`).

- [ ] **Step 4: Rework `start_task`**

Replace the single `_check_pipeline_predecessors(...)` call with:

```python
# (after the single-active-task guard block)
board_blockers_list = await self._board_blockers.get_unresolved_blockers(task_id)
feature_tasks = await self._board_repo.get_tasks_for_feature(task.feature_id)
pipeline_blockers = self._collect_pipeline_blockers(task, feature_tasks)
all_blockers = board_blockers_list + pipeline_blockers
if all_blockers:
    raise TaskBlockedError(task, all_blockers)
```

`TaskBlockedError` is a new exception carrying `task`, `blockers`, `code="task_blocked"`. Define it in `src/agent/exceptions.py` (new file if absent).

- [ ] **Step 5: Rework `update_task_status`**

Inside the service, before any write that would set `status="in_progress"`:

```python
if status == "in_progress":
    board_blockers_list = await self._board_blockers.get_unresolved_blockers(task_id)
    feature_tasks = await self._board_repo.get_tasks_for_feature(task.feature_id)
    pipeline_blockers = self._collect_pipeline_blockers(task, feature_tasks)
    all_blockers = board_blockers_list + pipeline_blockers
    if all_blockers:
        raise TaskBlockedError(task, all_blockers)
```

- [ ] **Step 6: Translate in the route layer**

Each handler keeps its **existing** `ValueError` mapping (they differ — don't copy-paste). Only the new `TaskBlockedError` catch is added.

`start_task` handler:
```python
try:
    return await service.start_task(worktree_id, body.task_id)
except TaskBlockedError as e:
    raise HTTPException(status_code=409, detail={
        "code": "task_blocked",
        "message": f"Cannot start task T-{e.task.number}: {len(e.blockers)} blocker(s) not resolved.",
        "blockers": e.blockers,
    }) from None
except ValueError as e:  # unchanged from today
    status = 409 if "Cannot start" in str(e) else 404
    raise HTTPException(status_code=status, detail=str(e)) from None
```

`update_task_status` handler — **keeps today's flat 409 for all `ValueError`** (it covers missing-`pr_url`-on-review, agent-cannot-move-to-done, etc.; `mcp-server/tests/server.test.ts` asserts these as 409-based failures). Do **not** introduce a 404 branch here.

```python
try:
    await service.update_task_status(...)
except TaskBlockedError as e:
    raise HTTPException(status_code=409, detail={
        "code": "task_blocked",
        "message": f"Cannot start task T-{e.task.number}: {len(e.blockers)} blocker(s) not resolved.",
        "blockers": e.blockers,
    }) from None
except ValueError as e:  # UNCHANGED — existing contract is 409-for-all
    raise HTTPException(status_code=409, detail=str(e)) from None
```

- [ ] **Step 7: Route-composition wiring**

In the `start_task` and `update_task_status` route handlers, construct `AgentService` as:

```python
board_repo = BoardRepository(session)
board_service = BoardService(board_repo)
service = AgentService(
    repo=AgentRepository(session),
    board_repo=board_repo,
    board_blockers=board_service,
)
```

Update `src/agent/routes.py`'s existing `ServiceDep` pattern (or equivalent) accordingly.

- [ ] **Step 8: Update all fixtures**

Every `AgentService(...)` call in `tests/agent/conftest.py` needs the new argument. Use a real `BoardService` over the same session — no mocks (project rule).

### Task A3: Integration tests for the feature-level guard

**Files:**
- Create or extend: `tests/agent/test_start_task_blockers.py`

- [ ] **Step 1: Cross-worktree feature-blocker happy path**

Two features F-A (upstream) and F-B (downstream) with one task each. Add dep F-B→F-A. F-A's task in `backlog` → `start_task` on F-B's task returns 409 with one `kind=feature` blocker listing `incomplete_task_numbers=[<F-A task #>]`.

- [ ] **Step 2: Feature-blocker resolves on PR-in-review**

Mutate F-A's task to `review` + `pr_url` → `start_task` succeeds.

- [ ] **Step 3: Feature-blocker resolves on done**

Mutate F-A's task to `done` → `start_task` succeeds (redundant safety check).

- [ ] **Step 4: Pipeline blocker alone**

Spec task + plan task in same feature, no feature deps. Plan task before spec's PR lands with artifact → 409 with one `kind=pipeline` blocker, `reason="not_done"` or `"artifact_missing"` depending on state. Assert message substring survives (compat with any log scrapers).

- [ ] **Step 5: Combined feature + pipeline**

Both blockers active → 409 with two entries, feature first, pipeline second.

- [ ] **Step 6: Same-worktree active-task guard fires first**

Worktree W, tasks T1 and T2 (T2 has feature dep to an incomplete upstream). Start T1 on W, then try `start_task(T2)` on W. Assert 409 with the legacy string `"Cannot start task: agent already has active task(s)"` — the active-task guard must fire **before** the blocker guard. Do not assert on structured `task_blocked` here.

- [ ] **Step 7: `update_task_status` mirrors the guard**

Same setup as Step 1 but call `update_task_status(task_id, "in_progress")` directly → 409 with the same structured payload.

- [ ] **Step 8: Run the full test suite**

```bash
uv run pytest tests/agent/ tests/board/ -v --tb=short
```

### Task A4: Update MCP client to preserve structured errors

**Files:**
- Modify: `mcp-server/src/client.ts`
- Create: `mcp-server/src/errors.ts`
- Modify: `mcp-server/src/server.ts` (handlers for `start_task`, `update_task_status`)
- Modify: `mcp-server/tests/client.test.ts` (if missing the error shape test, add it)

- [ ] **Step 1: Add the error class**

```typescript
// mcp-server/src/errors.ts
export interface StructuredDetail {
  code?: string
  message?: string
  blockers?: Array<Record<string, unknown>>
  [key: string]: unknown
}

export class CloglogApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string | StructuredDetail,
  ) {
    const msg = typeof detail === "string"
      ? `cloglog API error: ${status} ${detail}`
      : `cloglog API error: ${status} ${detail.message ?? JSON.stringify(detail)}`
    super(msg)
    this.name = "CloglogApiError"
  }

  get code(): string | undefined {
    return typeof this.detail === "object" ? this.detail.code : undefined
  }
}
```

- [ ] **Step 2: Update `request()` in `client.ts`**

Replace the current non-2xx branch:

```typescript
if (!response.ok) {
  const contentType = response.headers.get("content-type") ?? ""
  if (contentType.includes("application/json")) {
    const body = await response.json() as { detail?: string | StructuredDetail }
    throw new CloglogApiError(response.status, body.detail ?? JSON.stringify(body))
  }
  const text = await response.text()
  throw new CloglogApiError(response.status, text)
}
```

- [ ] **Step 3: Update the `start_task` / `update_task_status` handlers in `server.ts`**

Wrap the handler body:

```typescript
try {
  return await toolHandlers.start_task(args)
} catch (e) {
  if (e instanceof CloglogApiError && e.code === "task_blocked") {
    const detail = e.detail as StructuredDetail
    const lines = [
      detail.message ?? "Task is blocked.",
      ...(detail.blockers ?? []).map(formatBlocker),
    ]
    return { content: [{ type: "text", text: lines.join("\n") }], isError: true }
  }
  throw e
}

function formatBlocker(b: Record<string, unknown>): string {
  switch (b.kind) {
    case "feature":
      return `  - Feature F-${b.feature_number} "${b.feature_title}" (incomplete tasks: ${(b.incomplete_task_numbers as number[]).map(n => `T-${n}`).join(", ")})`
    case "task":
      return `  - Task T-${b.task_number} "${b.task_title}" (${b.status})`
    case "pipeline":
      return `  - Pipeline: ${b.predecessor_task_type} T-${b.task_number} "${b.task_title}" (${b.status}, reason=${b.reason})`
    default:
      return `  - ${JSON.stringify(b)}`
  }
}
```

- [ ] **Step 4: Build and test the MCP server**

```bash
cd mcp-server && make build && make test
```

### Task A5: Introduce `CurrentMcpOrDashboard` hybrid dependency

**Why not the original "Boy Scout `CurrentMcpService` on feature-dep routes" step:** the existing feature-dep tests in `tests/board/test_dependencies.py` use the shared dashboard-key `client` fixture (no `X-MCP-Request` header). Swapping to `CurrentMcpService` would 403-reject every existing caller. A hybrid dependency that accepts either credential shape closes the MCP-key-validation gap **without** forcing dashboard-key callers to change, which is what the middleware currently implements implicitly but un-validated.

**Files:**
- Modify: `src/gateway/auth.py` (add `CurrentMcpOrDashboard`)
- (Applied in Task B5 to the new task-dep routes.)

- [ ] **Step 1: Add the dependency**

```python
# src/gateway/auth.py
async def get_mcp_or_dashboard(request: Request) -> None:
    """Accept either a valid MCP service key OR a valid dashboard key.

    - If X-MCP-Request is present, require Authorization: Bearer <mcp_service_key>.
    - Else, require X-Dashboard-Key matching settings.dashboard_key.

    The middleware has already done a first-pass check (MCP header presence
    OR dashboard key presence), but does not validate the MCP service key.
    This dependency closes that gap on routes that opt in.
    """
    mcp_header = request.headers.get("X-MCP-Request")
    if mcp_header:
        token = _extract_bearer_token(request) or ""
        if not hmac.compare_digest(token, settings.mcp_service_key):
            raise HTTPException(status_code=401, detail="Invalid MCP service key")
        return

    dash = request.headers.get("X-Dashboard-Key") or request.query_params.get("dashboard_key")
    if dash and hmac.compare_digest(dash, settings.dashboard_key):
        return

    raise HTTPException(status_code=401, detail="Missing or invalid credentials")


CurrentMcpOrDashboard = Annotated[None, Depends(get_mcp_or_dashboard)]
```

- [ ] **Step 2: Unit tests for the helper**

Add to `tests/gateway/test_auth.py`:
- Valid MCP shape → passes.
- MCP shape with wrong token → 401.
- Valid dashboard key → passes.
- No credentials → 401.

- [ ] **Step 3: Do NOT retrofit existing feature-dep routes in this wave**

The existing MCP-only-gap on `POST/DELETE /features/{id}/dependencies` is a known-but-deferred issue. Follow-up ticket to apply `CurrentMcpOrDashboard` across all board write routes (not just deps) once the helper is merged — single-route retrofit risks inconsistent auth. Note this in the PR A description as a follow-up item.

### Task A6: Quality gate + PR

- [ ] `make quality`
- [ ] Invoke `/cloglog:demo` — backend PR, so use Showboat `exec` blocks to curl the guard on a real worktree port (show 409 with structured body when a feature blocker exists, 200 when resolved).
- [ ] Create PR with title `feat(agent): T-36 feature-level dependency guard at start_task`.
- [ ] `update_task_status` to `review` with PR URL.

---

## PR B — T-224: Task-level dependencies (table + routes + MCP tools + port extension)

Scope: extend `BoardBlockerQueryPort` to emit task blockers, add the data model, routes, and MCP tools. Builds on the guard plumbing from PR A.

### Task B1: Alembic migration for `task_dependencies`

**Files:**
- Create: `src/alembic/versions/<new_hash>_add_task_dependencies.py`

- [ ] **Step 1: Re-check current head on main**

```bash
git fetch origin main
git log origin/main -- src/alembic/versions/ | head -20
uv run alembic history | head -5
```

Record the current head revision. If a newer migration has landed since the spec was written, set `down_revision` to the new head.

- [ ] **Step 2: Generate migration**

```bash
uv run alembic revision -m "add_task_dependencies"
```

Edit the generated file:

```python
def upgrade() -> None:
    op.create_table(
        "task_dependencies",
        sa.Column("task_id", sa.UUID(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("depends_on_task_id", sa.UUID(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True),
        sa.CheckConstraint("task_id <> depends_on_task_id", name="ck_task_dep_no_self_loop"),
    )
    op.create_index(
        "ix_task_dependencies_depends_on_task_id",
        "task_dependencies",
        ["depends_on_task_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_task_dependencies_depends_on_task_id", table_name="task_dependencies")
    op.drop_table("task_dependencies")
```

- [ ] **Step 3: Spawn `migration-validator`**

```
Agent(subagent_type="migration-validator", ...)
```

Let it verify revision chain + upgrade/downgrade + model imports.

- [ ] **Step 4: Apply locally**

```bash
make db-migrate
```

### Task B2: ORM + repository methods

**Files:**
- Modify: `src/board/models.py` (extend `Task` with `dependencies` / `dependents`)
- Modify: `src/board/repository.py` (add five new methods)

- [ ] **Step 1: Relationships on `Task`**

```python
# src/board/models.py
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

- [ ] **Step 2: Repository methods**

```python
# src/board/repository.py
async def add_task_dependency(self, task_id: UUID, depends_on_task_id: UUID) -> None
async def remove_task_dependency(self, task_id: UUID, depends_on_task_id: UUID) -> bool
async def get_task_dependency_exists(self, task_id: UUID, depends_on_task_id: UUID) -> bool
async def get_task_dependencies(self, task_id: UUID) -> list[UUID]
async def get_all_task_dependencies(self, project_id: UUID) -> list[tuple[UUID, UUID]]
```

Mirror the feature-dep implementations line-for-line — copy `add_dependency` / `remove_dependency` / etc., s/feature/task/g, s/feature_dependencies/task_dependencies/g.

- [ ] **Step 3: Repository tests**

Create `tests/board/test_task_dependencies.py` mirroring the feature-dep test patterns: add, remove, exists, get-all.

### Task B3: Service-level cycle detection + same-project validation

**Files:**
- Modify: `src/board/services.py` (add `has_task_cycle`, `add_task_dependency`, `remove_task_dependency`)

- [ ] **Step 1: Cycle detection**

DFS from `depends_on_task_id`'s own dependencies, looking for `task_id`. Mirror `has_cycle` for features.

- [ ] **Step 2: `add_task_dependency`**

Validates (in order):
1. Self-loop → `ValueError("A task cannot depend on itself")`
2. Both tasks exist → `ValueError("Task not found")`
3. Same project (walk task→feature→epic→project on both sides) → `ValueError("Tasks must be in the same project")`
4. Duplicate → `ValueError("DUPLICATE")`
5. Cycle → `ValueError("Adding this dependency would create a cycle")`

- [ ] **Step 3: Service tests**

Add to `tests/board/test_task_dependencies.py`: self-loop, cross-project, cycle, duplicate, happy path. Use real `BoardService` over the test session (no mocks).

### Task B4: Extend `get_unresolved_blockers` to also emit task blockers

**Files:**
- Modify: `src/board/services.py`

- [ ] **Step 1: Append task-blocker pass**

After the feature-blocker loop in `get_unresolved_blockers`:

```python
dep_task_ids = await self._repo.get_task_dependencies(task_id)
for dep_tid in sorted(dep_task_ids):
    dep_task = await self._repo.get_task(dep_tid)
    if dep_task is None:
        continue
    if not _task_resolved(dep_task):
        blockers.append(TaskBlocker(
            kind="task",
            task_id=str(dep_task.id),
            task_number=dep_task.number,
            task_title=dep_task.title,
            status=dep_task.status,
        ))
```

Stable order: feature blockers first, task blockers second — matches spec.

- [ ] **Step 2: Extend the port test suite**

Add to `tests/board/test_blocker_query.py`: task blocker emitted on unresolved dep; task blocker suppressed on `done` / `review+pr_url`; combined feature + task blockers ordered correctly.

### Task B5: Routes for task-dep CRUD

**Files:**
- Modify: `src/board/routes.py` (add two handlers)
- Modify: `src/board/schemas.py` (add `TaskDependencyCreate` if not reusable)
- Modify: `src/shared/events.py` (no new enum — reuse `DEPENDENCY_ADDED` / `DEPENDENCY_REMOVED`)

- [ ] **Step 1: Handlers**

```python
@router.post("/tasks/{task_id}/dependencies", status_code=201)
async def add_task_dep(
    task_id: UUID,
    body: TaskDependencyCreate,
    service: ServiceDep,
    _: CurrentMcpOrDashboard,  # from PR A's Task A5
) -> dict[str, str]:
    try:
        await service.add_task_dependency(task_id, body.depends_on_id)
    except ValueError as e:
        msg = str(e)
        if "DUPLICATE" in msg:
            raise HTTPException(status_code=409, detail="Dependency already exists") from None
        raise HTTPException(status_code=400, detail=msg) from None
    # resolve project_id via task→feature→epic
    task = await service._repo.get_task(task_id)
    feature = await service._repo.get_feature(task.feature_id)
    epic = await service._repo.get_epic(feature.epic_id)
    await event_bus.publish(Event(
        type=EventType.DEPENDENCY_ADDED,
        project_id=epic.project_id,
        data={"scope": "task", "task_id": str(task_id), "depends_on_id": str(body.depends_on_id)},
    ))
    return {"status": "created"}


@router.delete("/tasks/{task_id}/dependencies/{depends_on_id}", status_code=204)
async def remove_task_dep(
    task_id: UUID,
    depends_on_id: UUID,
    service: ServiceDep,
    _: CurrentMcpOrDashboard,
) -> None:
    # mirror the pattern from remove_dependency for features, emit scope="task"
```

Tests use the existing shared dashboard-key `client` fixture from `tests/conftest.py` (same as feature-dep tests) — the hybrid dep accepts that path.

- [ ] **Step 2: Also update feature-dep events**

Add `"scope": "feature"` to the existing feature-dep event data payloads. Backwards-compatible (frontend ignores unknown fields; refetch is scope-agnostic). Do this in one commit so the old events don't linger without the discriminator.

- [ ] **Step 3: Route tests**

Add to `tests/board/test_task_dependencies.py`: POST happy path (201), POST duplicate (409), POST cycle (400), POST cross-project (400), DELETE happy path (204), DELETE unknown (404).

### Task B6: MCP tools for task deps

**Files:**
- Modify: `mcp-server/src/tools.ts`
- Modify: `mcp-server/src/server.ts`
- Modify: `mcp-server/tests/server.test.ts`

- [ ] **Step 1: Handlers in `tools.ts`**

```typescript
async add_task_dependency({ task_id, depends_on_id }) {
  return client.request('POST', `/api/v1/tasks/${task_id}/dependencies`, { depends_on_id })
},
async remove_task_dependency({ task_id, depends_on_id }) {
  return client.request('DELETE', `/api/v1/tasks/${task_id}/dependencies/${depends_on_id}`)
},
```

- [ ] **Step 2: Register tools in `server.ts`**

```typescript
server.tool('add_task_dependency', 'Add a blocked_by edge. Both tasks must be in the same project.',
  { task_id: z.string(), depends_on_id: z.string() },
  wrapHandler(async ({ task_id, depends_on_id }) => toolHandlers.add_task_dependency({ task_id, depends_on_id })),
)

server.tool('remove_task_dependency', 'Remove a blocked_by edge.',
  { task_id: z.string(), depends_on_id: z.string() },
  wrapHandler(async ({ task_id, depends_on_id }) => toolHandlers.remove_task_dependency({ task_id, depends_on_id })),
)
```

- [ ] **Step 3: Build + test**

```bash
cd mcp-server && make build && make test
```

### Task B7: Same-worktree vs cross-worktree guard tests (extended matrix)

**Files:**
- Extend: `tests/agent/test_start_task_blockers.py`

- [ ] **Step 1: Cross-worktree task-blocker happy path (PR-in-review resolves)**

Two worktrees, two tasks T1 (upstream) and T2 (`T2 blocked_by T1`). W1 moves T1 to review with `pr_url`. W2 calls `start_task(T2)` → succeeds.

- [ ] **Step 2: Cross-worktree task-blocker reject**

T1 in `backlog`. W2 calls `start_task(T2)` → 409 with `kind=task` entry.

- [ ] **Step 3: Same-worktree chain requires `pr_merged=True`**

Worktree W, tasks T1 (upstream) and T2 (`blocked_by T1`). W moves T1 to review with `pr_url` (`pr_merged=False`). W calls `start_task(T2)` → 409 with legacy active-task-guard message. Then call `mark_pr_merged` on T1 → `start_task(T2)` now succeeds (both guards pass).

- [ ] **Step 4: Combined feature + task + pipeline**

Set up all three blockers at once. Assert three-entry payload in stable order.

### Task B8: Quality gate + PR

- [ ] `make quality`
- [ ] `/cloglog:demo` — Showboat script that:
  1. `add_task_dependency` via MCP against a real worktree session
  2. `start_task` returns 409 with structured blockers
  3. Resolve the blocker (move upstream to review+pr_url)
  4. `start_task` succeeds
  5. `remove_task_dependency` round-trips
- [ ] Create PR `feat(board,agent): T-224 task-level dependencies + guard extension`.
- [ ] `update_task_status` to `review` with PR URL.

---

## Risk notes

- **Concurrent migrations.** If another context lands a migration on `main` between PR A and PR B, PR B's `down_revision` needs updating during rebase. Re-run Task B1 Step 1 before push.
- **`start_task` is load-bearing.** Many callers. PR A's refactor from "raise" to "collect + raise-once" changes error messaging. Existing `"Cannot start"` substring assertions in `tests/e2e/test_state_machine.py` need to remain green — the legacy string survives for the active-task guard and for the fallback `ValueError` path; structured 409 is only for blocker cases. Run `make test-e2e` locally before pushing PR A.
- **MCP client change is fleet-wide.** The MCP server runs on the user's machine across all worktrees. After PR A merges, running MCP instances need a rebuild (`cd mcp-server && make build`). Call this out in the PR description.
- **Port naming collision.** There is no existing `BoardBlockerQueryPort`; `interfaces.py` currently wraps write-side services (`TaskAssignmentService`, `TaskStatusService`). Adding a read-shaped port is a first — keep the file structure clean (separate classes, same file).
- **Dogfood readiness (T-225).** T-225 needs the `add_task_dependency` MCP tool to be registered in the user's MCP client session. After T-224 merges, T-225's agent must restart its MCP server before the tool is callable — note this in T-225's start-of-session check.

## Open questions (none currently)

All design questions are resolved in the spec. If the reviewer surfaces anything new, update the spec first and link from the relevant task step here.

## References

- Spec: `docs/superpowers/specs/2026-04-19-task-and-feature-dependencies.md`
- Pattern: `docs/superpowers/plans/2026-04-05-dependency-graph.md` (feature-dep CRUD reference)
- DDD context map: `docs/ddd-context-map.md`
- CLAUDE.md — Cross-Context Integration (router registration, Alembic discipline)
