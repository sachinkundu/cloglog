# Backend-owned close-off task creation

**Status:** Spec (T-432) — frozen for implementation in T-433/T-434.
**Owner:** Agent context.
**Consumer:** close-wave skill Step 1.5; reconcile close-wave-delegation predicate.

## Why

Today the close-off row (`Close worktree <wt-name>`, status `backlog`,
assigned to the main agent) is created by the **per-project**
`.cloglog/on-worktree-create.sh` POSTing to `/api/v1/agents/close-off-task`
(see `plugins/cloglog/templates/on-worktree-create.sh` lines ~155-190 in
the cloglog tree).

That makes the invariant "every worktree has a paired close-off row"
plugin-portable only if every downstream project copies the POST block
into its own bootstrap. The antisocial repo demonstrates the failure
mode: its `on-worktree-create.sh` does no such POST, so worktrees there
launch with no close-off shadow on the board, and reconcile's close-wave
delegation predicate (component 2) silently mis-fires for every cleanly
completed worktree on that host.

The fix is to move close-off-row creation **server-side**, into the
`register_agent` path. Per-project bootstrap scripts then keep their
project-specific responsibilities (npm ci, .env copy, Vite warm-up) and
lose the close-off POST entirely. The invariant becomes a property of the
backend, not a property of a particular plugin's templated shell script.

## Trigger event

**Decision:** trigger inside `register_agent` (`src/agent/services.py`),
on the **first** call for a given `worktree_path` within a project.
"First" is keyed on the worktree row, not the session: the supervisor
calls `register_agent` once at launch, the worktree-agent process calls
it again from inside the worktree, and any later resume calls it again
after a crash + relaunch — the close-off row is filed exactly once across
all of those.

We considered a separate `worktree_create` lifecycle event the backend
mints when it sees an unseen worktree row. Rejected: it adds a second
event source that downstream consumers (close-wave, reconcile) would
have to subscribe to, with no benefit over piggy-backing on
`register_agent`. The two events would always fire together; one of them
is redundant.

The hook fires **after** the worktree row is committed by
`register_agent` and **before** the response is returned, so the caller
that gets back `worktree_id` can immediately rely on the close-off row
existing on the board. Failure to file the close-off row is **not**
fatal to `register_agent` — see *Failure handling* below.

## Idempotency

The natural key is `close_off_worktree_id` — the FK from the close-off
task row back to the worktree it closes. `BoardRepository.find_close_off_task(close_off_worktree_id)`
is the existing dedup primitive (`src/board/services.py:430`). Reuse it.

Concretely:

1. `register_agent` resolves (or creates) the worktree row by
   `(project_id, worktree_path)`.
2. After commit, call
   `BoardService.create_close_off_task(project_id, close_off_worktree_id=worktree.id, worktree_name=worktree.name, main_agent_worktree_id=...)`.
3. That service already returns `(task, created)` with `created=False`
   on idempotent hits — the spec adds no new dedup logic, only a new
   call site.

A re-registered worktree (same path, new session_id) hits step 1 with
the same worktree row (the row is keyed on `worktree_path`, sessions
hang off it) and so step 2 short-circuits at the existing close-off
row. **No duplicate ever lands.**

## Force-unregister and re-register

Force-unregister marks the worktree row inactive but does not delete it
or its close-off task. If the worktree is later re-registered (rare but
the path is exercised by reconcile self-heal flows):

- If the existing close-off row is still in `backlog` → reuse it. The
  natural-key lookup already returns it; nothing to do.
- If the existing close-off row is in `in_progress` / `review` / `done`
  → **do not** file a new one. The original row tracks the same
  worktree's teardown work; a second row for the same `close_off_worktree_id`
  would either violate the unique constraint (if we add one) or
  duplicate the supervisor's close-off card.

Implementation note: the `find_close_off_task` lookup is unconditional
on status, so the natural-key path already does the right thing. We do
**not** need a "create-new-if-status-not-backlog" branch — that was
considered and rejected because it lets a single worktree accumulate
multiple close-off rows over its lifetime, which breaks close-wave's
1:1 assumption (`close_off_task_ids[wt-name] → task_uuid`).

If operationally we ever need to re-open teardown for a worktree whose
close-off was already closed, that's a manual board action (move the
existing task back to `backlog`), not a re-creation.

## Project opt-out

**Decision:** no opt-out flag. The close-off row is always created.

Rationale:

- The row is cheap (one INSERT plus the auto-provisioned epic/feature
  on first use within a project).
- Downstream projects that don't run close-wave simply ignore the row;
  it sits in `backlog` until manually disposed of, no different from
  any other unprioritised task.
- Adding `enable_close_off_rows` to `.cloglog/config.yaml` introduces a
  knob whose only legitimate setting is `true` — every project that
  runs cloglog at all benefits from the row, and projects that don't
  run cloglog don't reach this code path.
- A per-project flag would have to be checked inside the backend on
  every `register_agent` call, threading config through a layer that
  currently only knows about projects, agents, and tasks. The DDD
  boundary cost outweighs the (zero) operator benefit.

## Per-project task title format

**Decision:** preserve the exact existing format,
`Close worktree <wt-name>`, where `<wt-name>` is the worktree's
short name (e.g. `wt-t432-close-off-spec`).

This is non-negotiable: close-wave Step 1.5 hard-codes
`title == f"Close worktree {wt-name}"` as the lookup predicate
(`plugins/cloglog/skills/close-wave/SKILL.md:31, 87`). Changing the
title shape silently breaks every existing close-wave run.

The title is generated by `close_worktree_template(worktree_name)` in
`src/board/services.py` (called at line 469). The implementation must
keep that helper unchanged. The pin lives in
`tests/board/test_close_off_task.py` (or wherever the existing
`create_close_off_task` test pins title shape — implementation task
verifies and adds a pin if missing).

The body of the task description may evolve; the **title** is contract.

## Migration plan

Existing worktree rows that have no close-off task fall into two
groups:

1. **Active worktrees with no close-off row.** This is the case the
   backend trigger needs to backfill. After the new trigger ships,
   any subsequent `register_agent` resume call on these worktrees will
   land the row idempotently — but operators don't always resume every
   active worktree on day one.

   **Decision:** ship a one-shot Alembic data migration in the same
   PR as the trigger. The migration scans `worktrees` filtered to
   active rows (no `force_unregistered_at`, no later replacement at
   the same path) and calls the same `create_close_off_task` service
   for each. The migration is idempotent — re-running it is a no-op
   because the natural-key lookup short-circuits.

2. **Stale / closed / force-unregistered worktrees with no close-off
   row.** Leave alone. There is no useful teardown work to track on a
   worktree that is already gone; filing a backlog card for it would
   pollute the board with rows the supervisor cannot meaningfully
   action.

The migration runs forward only. Downgrade is a no-op (we do not
delete the backfilled rows on rollback — they are real teardown work
the operator may legitimately complete). This is documented on the
migration's `downgrade()` with a comment.

## Per-project agent-side workflow vs. backend trigger

After this feature, the per-project `on-worktree-create.sh` keeps:

- npm/uv installs and other warm-up the project needs.
- `.env` copy and any project-specific secret hydration.
- Echoing diagnostics (resolved backend URL, API key source) for
  bootstrap-time visibility.

It **loses**:

- The `curl POST /api/v1/agents/close-off-task` block (lines ~155-190
  in the cloglog template).
- The `_resolve_api_key` / `_resolve_backend_url` helpers if they are
  used only by that POST (verify in implementation; they are likely
  also used elsewhere — leave them if so).
- The fail-loud-on-HTTP-non-201 handling for that POST, since the
  POST is gone.

The HTTP route `/agents/close-off-task` itself stays — it is still
exposed by the MCP `mcp__cloglog__create_close_off_task` tool, which
the supervisor uses for one-off backfills. **Deleting the route is
out of scope.** Only the per-project script's *call site* is
removed; the route, the service method, and the MCP tool all remain.

The split is documented in the cloglog plugin's
`templates/on-worktree-create.sh` header comment plus a one-liner in
`docs/ddd-context-map.md` Agent context section: "Close-off row
creation is owned by the backend's `register_agent` path; per-project
bootstrap scripts do not POST it."

## Failure handling

If `create_close_off_task` raises inside the `register_agent` flow:

- **Database error** (FK violation, unique constraint, transient
  connection blip): roll back the close-off task creation but
  **commit** the worktree registration. `register_agent` returns
  success. The supervisor's invariant ("the agent is registered") is
  preserved; the close-off row gap is detected and self-healed by
  the next reconcile run (T-371 reconcile rule covers this).
- **Programmer error** (KeyError, AttributeError on a missing
  `worktree.name`, etc.): log loud, return success on
  `register_agent`, file an `mcp_tool_error` style backend log so
  the supervisor sees it. Do not block the agent from launching.
- **Migration concurrency** (the one-shot backfill running while a
  fresh `register_agent` lands): both call the same idempotent
  service; whichever loses the race short-circuits on the natural-key
  lookup. No special handling.

The principle: `register_agent` is the agent lifecycle's load-bearing
event. The close-off row is **important but not critical** to that
event succeeding. A close-off row gap is detectable and self-healing
via reconcile; a `register_agent` failure cascades into the agent
never starting at all. The trigger is best-effort within
`register_agent`'s success path, not a synchronous gate on it.

## Out of scope

- The actual SQLAlchemy / Alembic code (T-434 implementation).
- Test wiring and pin tests (T-433 plan, T-434 implementation).
- Removing the per-project POST block from `on-worktree-create.sh`
  (T-434 implementation; the script edit lands in the same PR as the
  backend trigger so the two halves stay in sync).
- Deprecating or deleting the `/agents/close-off-task` HTTP route or
  the `mcp__cloglog__create_close_off_task` MCP tool — both stay as
  one-off backfill affordances for the supervisor and reconcile.
- Any change to the close-off task title shape.
- Any change to close-wave's Step 1.5 lookup predicate.

## Pins this spec carries

The implementation PR (T-434) MUST add or verify these pin tests:

1. `register_agent` first call for a new `worktree_path` files exactly
   one close-off row.
2. Second `register_agent` call for the same `worktree_path` (resume,
   crash + relaunch) does **not** file a duplicate.
3. Re-registration of a force-unregistered worktree reuses the
   existing close-off row regardless of its current status.
4. Title is exactly `Close worktree <wt-name>`.
5. Close-off-task creation failure does NOT fail the
   `register_agent` call.
6. The one-shot data migration is idempotent (re-running over a
   fully-backfilled DB makes no changes).
