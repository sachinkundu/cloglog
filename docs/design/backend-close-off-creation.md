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
2. After commit, derive the worktree name with the existing rule
   `worktree_name = worktree.branch_name or worktree.worktree_path.rsplit("/", 1)[-1]`
   — the `Worktree` ORM model (`src/agent/models.py:24`) has no `name`
   field; that derivation is what `services.py` already uses elsewhere
   (e.g. line 770 in the unregister log path). Then call
   `BoardService.create_close_off_task(project_id, close_off_worktree_id=worktree.id, worktree_name=worktree_name, main_agent_worktree_id=...)`.
3. That service already returns `(task, created)` with `created=False`
   on idempotent hits — the spec adds no new dedup logic, only a new
   call site.

A re-registered worktree (same path, new session_id) hits step 1 with
the same worktree row (the row is keyed on `worktree_path`, sessions
hang off it) and so step 2 short-circuits at the existing close-off
row. **No duplicate ever lands.**

## Force-unregister and re-register

The reusable-row plan I considered first (and codex correctly rejected)
is **incompatible with the current data model**. Two facts force the
hand:

- `AgentService.force_unregister` (`src/agent/services.py:773, 837`)
  **deletes** the `worktrees` row outright — there is no inactive
  tombstone.
- The close-off FK is `ON DELETE SET NULL` (Alembic
  `d2a1b3c4e5f6_add_close_off_worktree_id_to_tasks.py` lines 41-48).
  When the worktree row is deleted, `tasks.close_off_worktree_id` on
  the existing close-off card is silently cleared. The card lingers on
  the board but is no longer reachable through the natural-key lookup
  `find_close_off_task(close_off_worktree_id)`.

Therefore: when the same `worktree_path` is registered again after a
force-unregister, it gets a brand-new worktree UUID. The old close-off
card has `close_off_worktree_id = NULL`; the lookup against the new
UUID misses; the trigger files **a new** close-off row.

**Decision (revised):** re-register after force-unregister files a new
close-off row. The original card stays on the board with
`close_off_worktree_id = NULL` — that is the documented "lingers on
backlog as a flag" behaviour from the migration's docstring (lines
9-13). Operators who notice the orphan can dispose of it manually; it
does not break correctness because close-wave's Step 1.5 lookup is
predicated on `status == "backlog"` AND the worktree being **active**
(via the per-worktree map built from currently-known `wt-name`s), so a
stale card whose worktree is gone never enters the close-wave fold.

This raises one consumer concern that the implementation PR (T-434)
must address: **close-wave Step 1.5 keys on title equality** within
the set of *currently active* worktrees
(`plugins/cloglog/skills/close-wave/SKILL.md:87`). If a `wt-x` is
force-unregistered then re-created at the same path *while the old
close-off card is still in `backlog` status*, Step 1.5's
`title == "Close worktree wt-x"` filter sees two backlog rows and
errors with ambiguous match.

The fix lives in close-wave (T-434 implementation owns the edit):
filter Step 1.5's title lookup by `close_off_worktree_id IS NOT NULL`
in addition to title and backlog status. That is sufficient because
the migration's `ON DELETE SET NULL` guarantees orphaned cards from
deleted worktrees are exactly those with NULL FK — the live card from
the re-registration is the only remaining match. This is a one-line
predicate change, pinned by a new test in
`tests/plugins/test_close_wave_skill.py` (or wherever Step 1.5
lookups are exercised).

Reconcile (T-371 rule) keeps owning the wider self-heal: if a
worktree is active but has no close-off card with
`close_off_worktree_id = worktree.id`, it files one. That covers both
the "trigger ran and failed silently" gap and the "orphan card
exists, no live card" gap.

If operationally we ever need to re-open teardown for a worktree
whose close-off was already closed, that's a manual board action
(move the existing task back to `backlog`) — but only if the worktree
is still alive. After force-unregister, the "re-open" affordance is
gone with the row.

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
   PR as the trigger. The migration scans currently-existing
   `worktrees` rows (force-unregister deletes rows, so any row still
   present is by definition active) and, for each, **resolves the
   main-agent worktree using the same role/env fallback the HTTP
   route uses** (`src/agent/routes.py:357-378`: prefer
   `AgentRepository.get_main_agent_worktree(project_id)`, fall back
   to the worktree at `settings.main_agent_inbox_path.parent.parent`,
   else `None`) before calling
   `BoardService.create_close_off_task(..., main_agent_worktree_id=...)`.
   Skipping the resolver would create rows with `worktree_id = NULL`,
   breaking the visibility contract pinned by
   `tests/agent/test_close_off_task.py:521-565` (close-off must surface
   in the main agent's `mcp__cloglog__get_my_tasks`) — the same T-305
   regression the route already defends against.

   The migration is idempotent — re-running it is a no-op because the
   natural-key `find_close_off_task` lookup short-circuits. The
   resolver is best-effort: when no main agent is registered (a
   downstream project that never ran `/cloglog setup`), the row is
   filed unassigned, exactly matching the live trigger's behaviour
   for the same condition.

   **Concurrency.** The migration and live `register_agent` calls can
   race: both pass `find_close_off_task` before either inserts the
   FK; the loser then hits the
   `uq_tasks_close_off_worktree_id` unique index
   (Alembic `d2a1b3c4e5f6` lines 49-54), aborting the transaction.
   Two acceptable mitigations — pick one in T-434:

   - **(Preferred)** Wrap `create_close_off_task` in a
     catch-`IntegrityError` → rollback → re-read with
     `find_close_off_task` → return the existing row. This makes the
     service genuinely upsert-shaped without restructuring it as a
     SQL `INSERT ... ON CONFLICT`. The same handler covers the live
     trigger's race against itself in pathological double-call
     scenarios.
   - **Quiesce live registrations during the migration.** Acceptable
     for cloglog (single host, operator-driven `make migrate`) but
     not portable to downstream projects that may run migrations
     under load. Document the constraint in the migration docstring
     if chosen.

   The "no special handling" line in the prior draft was wrong;
   codex caught it.

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

- **`IntegrityError` on `uq_tasks_close_off_worktree_id`** (the
  migration / re-entrant register race described under *Migration
  plan / Concurrency*): catch, rollback the close-off insert,
  re-read with `find_close_off_task(close_off_worktree_id)`, return
  the existing row. This is a clean idempotent hit, not a failure.
- **Other database error** (FK violation against a deleted parent,
  transient connection blip): roll back the close-off task creation
  but **commit** the worktree registration. `register_agent` returns
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
   one close-off row, with `worktree_id` set to the resolved main
   agent (or NULL if none registered, surfacing the existing
   diagnostic warning).
2. Second `register_agent` call for the same `worktree_path` (resume,
   crash + relaunch) does **not** file a duplicate.
3. Re-registration after `force_unregister` files a **new** close-off
   row keyed on the new worktree UUID. The old card lingers with
   `close_off_worktree_id = NULL` and is filtered out by close-wave's
   updated Step 1.5 predicate.
4. Title is exactly `Close worktree <wt-name>` where `<wt-name>` is
   `worktree.branch_name or worktree.worktree_path.rsplit("/", 1)[-1]`.
5. Close-off-task creation failure does NOT fail the
   `register_agent` call.
6. The migration/race `IntegrityError` path returns the existing row
   instead of propagating (concurrent migration + live register on
   the same worktree → exactly one row, no aborted transaction).
7. The one-shot data migration is idempotent (re-running over a
   fully-backfilled DB makes no changes) AND resolves
   `main_agent_worktree_id` so backfilled rows surface in
   `mcp__cloglog__get_my_tasks` per the
   `tests/agent/test_close_off_task.py:521-565` visibility contract.
8. Close-wave Step 1.5 lookup is filtered by
   `close_off_worktree_id IS NOT NULL` so a re-registered worktree
   with a stale orphan card does not produce an ambiguous title
   match.
