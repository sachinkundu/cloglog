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

**Decision:** trigger at the **route/composition layer**
(`src/agent/routes.py`, the `register_agent` POST handler), on the
**first** call for a given `worktree_path` within a project. The
route already plays the cross-context orchestrator role today —
`/agents/close-off-task` resolves a worktree, looks up the main
agent, and then calls `BoardService.create_close_off_task`
(`routes.py:346-378`). The new path mirrors that shape: the route
calls `AgentService.register(...)` first, then — for `role='worktree'`
rows on the first registration — calls
`BoardService.create_close_off_task(...)`. This keeps the cross-context
boundary clean: `AgentService` does not gain a direct dependency on
`BoardService`, and `src/board/interfaces.py` does not need a new
"ensure close-off" port (the existing route-layer composition is the
documented seam).
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

The hook fires inside the same route handler invocation as
`register_agent`, ordered so that close-off creation happens **before
the registration's commits and `WORKTREE_ONLINE` event are visible to
other consumers** (see *Failure handling* below — the current
`AgentService.register` flow needs T-434 plumbing work to defer those
emissions). For `role='worktree'` first registrations, failure to
file the close-off row is **fatal** to `register_agent`; the route
returns 5xx and no online state is leaked. This matches the existing
`.cloglog/on-worktree-create.sh` fail-loud contract from T-378.

**Role gate — `role='worktree'` only.** `register_agent` is also
called by the supervisor's `/cloglog setup` from the main checkout
(`plugins/cloglog/skills/setup/SKILL.md:25-31`); that registration
gets `role='main'` because the path lacks the
`/.claude/worktrees/` marker (`src/agent/services.py:34, 147`). The
main checkout has no teardown semantics — close-wave only targets
paths under `.claude/worktrees/`
(`plugins/cloglog/skills/close-wave/SKILL.md:81-88`) — so filing a
`Close worktree <main-clone-name>` card for it would create a
permanent backlog ghost on every supervisor's `get_my_tasks`. The
trigger therefore guards on `worktree.role == 'worktree'` and
short-circuits for `role='main'`. The same gate applies to the
backfill migration's source query.

## Idempotency

The natural key is `close_off_worktree_id` — the FK from the close-off
task row back to the worktree it closes. `BoardRepository.find_close_off_task(close_off_worktree_id)`
is the existing dedup primitive (`src/board/services.py:430`). Reuse it.

Concretely:

1. `register_agent` resolves (or creates) the worktree row by
   `(project_id, worktree_path)`.
2. **In the route handler (not in `AgentService`),** after
   `service.register(...)` returns, gate on
   `worktree.role == 'worktree'`. For `role='main'` registrations,
   skip the rest of this step — those carry no teardown
   semantics (see *Role gate* above).
3. Derive the worktree name with the existing rule
   `worktree_name = worktree.branch_name or worktree.worktree_path.rsplit("/", 1)[-1]`
   — the `Worktree` ORM model (`src/agent/models.py:24`) has no `name`
   field; that derivation is what `services.py` already uses elsewhere
   (e.g. line 770 in the unregister log path).
4. Resolve `main_agent_worktree_id` using the same role/env fallback
   as the existing `/agents/close-off-task` route
   (`routes.py:357-378`).
5. Call
   `BoardService.create_close_off_task(project_id, close_off_worktree_id=worktree.id, worktree_name=worktree_name, main_agent_worktree_id=...)`.
   That service already returns `(task, created)` with `created=False`
   on idempotent hits — the spec adds no new dedup logic, only a new
   call site at the route layer.

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

The fix is two-step and **scope-expands T-434** to include a board
API contract change:

1. **Surface `close_off_worktree_id` on `TaskCard` /
   `TaskResponse`** (`src/board/schemas.py:161-213`). The field is
   nullable on the model already; it just isn't carried through the
   response schema, so `mcp__cloglog__get_board()` cannot expose it
   today (`src/board/routes.py:686-694`). Add it to both schemas as
   `Optional[UUID]`. This is additive — no consumer breaks.
2. **Move close-wave's worktree inventory to Step 1, then filter
   Step 1.5 by `close_off_worktree_id == <expected worktree UUID>`**
   (not just `IS NOT NULL`). Today close-wave Step 1 discovers
   worktree *names* from `git worktree list`
   (`plugins/cloglog/skills/close-wave/SKILL.md:81-88`) and only
   fetches `worktree_id` later in Step 5a (line 129-137). The new
   FK-based predicate runs in Step 1.5, which is between those — so
   T-434 must lift the inventory call earlier. Mirror reconcile's
   pattern (`plugins/cloglog/skills/reconcile/SKILL.md:48-67`): call
   `mcp__cloglog__list_worktrees()` first, build the
   `wt-name → worktree_id` map, then run the close-off lookup
   keyed on `close_off_worktree_id == map[wt-name]`. Title equality
   becomes a defensive sanity assertion, not the load-bearing
   predicate.

Reconcile (T-371 rule) gets the same FK-based predicate update so
its close-wave-delegation component does not regress on the same
ambiguity.

Both edits land in the same T-434 PR as the trigger and migration so
the consumer contract and the producer contract ship in lockstep.
Pinned by a new test in `tests/plugins/test_close_wave_skill.py` (or
wherever Step 1.5 lookups are exercised) plus the existing
`tests/board/test_schemas.py` getting a `close_off_worktree_id` round-trip
case.

Codex round 2 caught that the prior "filter by `IS NOT NULL`" plan
was unimplementable — `TaskCard` does not expose the field — so the
schema change is non-negotiable for the design to be consistent.

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

   **Decision:** ship a one-shot **application-level backfill
   command** in the same PR as the trigger (see *Application-level
   command, not Alembic* below for why this is not an Alembic data
   migration). The command scans `worktrees` rows filtered to
   **`status = 'online' AND role = 'worktree'`**. The
   `role = 'worktree'` predicate excludes the supervisor's main
   checkout from the backfill for the same reason the live trigger
   excludes it (above).

   "Row exists" is **not** equivalent to "active": heartbeat
   timeouts set `status = 'offline'` without deleting
   (`src/agent/services.py:879-916`); only `force_unregister`
   (`services.py:773, 837`) and `remove_offline_agents`
   (`services.py:866-874`) delete rows. Backfilling close-off cards
   for offline rows would pollute the board with teardown work for
   crashed agents — exactly the "stale/closed worktrees get nothing"
   case the spec excludes.

   **Application-level command, not Alembic.** The original draft
   said the migration should reproduce close-off creation in sync
   SQL inside `upgrade()`. Codex round 4 correctly rejected that:
   `BoardService.create_close_off_task` is not a bare insert. It
   allocates numbers via `next_epic_number` /
   `next_feature_number` / `next_task_number`
   (`src/board/services.py:434-470`,
   `src/board/repository.py:92`), routes the task insert through
   `BoardService.create_task` whose contract recomputes feature/epic
   rollups when a task is added to a `done` feature
   (`src/board/services.py:140`), and the sequential-numbering
   contract is API-pinned at
   `tests/e2e/test_board_consistency.py:223`. A SQL replay would
   silently regress all three: backfilled cards could land in a
   `done` close-off feature without re-opening it, and the migration
   could consume `next_*_num` slots that the API later reuses.

   **Decision:** the backfill ships as an application-level
   maintenance command — `make backfill-close-off` (a thin wrapper
   around a `cloglog admin backfill-close-off` CLI subcommand, or
   equivalent — T-433 picks the exact spelling). The command opens
   an `AsyncSession`, iterates `worktrees.status='online' AND
   worktrees.role='worktree'`, resolves the main agent via the same
   route-layer fallback, and calls
   `BoardService.create_close_off_task(...)` for each. That reuses
   every service-side invariant exactly — numbering, rollups, the
   `IntegrityError` catch (see *Concurrency* below), and the same
   visibility contract pinned by `test_close_off_task.py:521-565`.

   The Alembic migration in the same PR carries **only** the
   schema additions: `close_off_worktree_id` on `TaskCard` /
   `TaskResponse` is a Pydantic-only change (no DB migration);
   if any DB column changes are needed (none expected, the FK
   already exists) they live in a sibling Alembic file. The
   operational ordering is:

   1. PR ships → schema change deploys.
   2. Operator runs `make backfill-close-off` once (idempotent —
      re-runs short-circuit on `find_close_off_task`).
   3. From this point on every new `register_agent` files its own
      close-off row via the trigger.

   The backfill command is documented in `docs/setup-credentials.md`
   adjacent to the existing `make migrate` instructions, and the
   release note for T-434 calls it out so operators on hosts with
   pre-existing worktrees do not skip it.

   For each `status='online' AND role='worktree'` row the backfill
   command **resolves the main-agent worktree using the same role/env
   fallback the HTTP route uses** (`src/agent/routes.py:357-378`: prefer
   `AgentRepository.get_main_agent_worktree(project_id)`, fall back
   to the worktree at `settings.main_agent_inbox_path.parent.parent`,
   else `None`) before calling
   `BoardService.create_close_off_task(..., main_agent_worktree_id=...)`.
   Skipping the resolver would create rows with `worktree_id = NULL`,
   breaking the visibility contract pinned by
   `tests/agent/test_close_off_task.py:521-565` (close-off must surface
   in the main agent's `mcp__cloglog__get_my_tasks`) — the same T-305
   regression the route already defends against.

   The backfill command is idempotent on the natural key — re-runs
   short-circuit inside `BoardService.create_close_off_task`. But
   the existing service path is **not** self-healing on
   `worktree_id` (`src/agent/routes.py:380-420` documents this:
   when a row exists with `worktree_id IS NULL`, idempotent re-calls
   do not backfill the assignee even if the resolver now succeeds —
   the warning at line 388 fires precisely on this pathology).

   That gives the backfill two unacceptable failure shapes if it
   runs without a main agent:

   1. Operator runs `make backfill-close-off` before
      `/cloglog setup` → unassigned rows lands → second run after
      setup is a no-op → rows never surface in the supervisor's
      `get_my_tasks`.
   2. Per-project resolver returns `None` because the
      `main_agent_inbox_path` env var is unset → same outcome.

   **Decision:** the backfill command **fails fast** if
   `AgentRepository.get_main_agent_worktree(project_id)` (with the
   documented env fallback) returns `None`. Exit non-zero with a
   message instructing the operator to run `/cloglog setup` first.
   The fail-fast guard is mandatory — best-effort here would
   silently regress the visibility contract pinned by
   `tests/agent/test_close_off_task.py:521-565`.

   T-434 also adds an idempotency-with-repair behaviour on the
   service: when `find_close_off_task` returns an existing row with
   `worktree_id IS NULL` AND the caller now resolves a main agent,
   the service backfills `worktree_id` on that existing row before
   returning. That covers two adjacent paths the current code does
   not — (a) the live trigger on a re-register after a downstream
   operator finally runs setup, and (b) a manual MCP
   `create_close_off_task` re-call. Pin obligation carried in #7.

   **Concurrency.** The backfill command and live `register_agent`
   calls can race: both pass `find_close_off_task` before either
   inserts the FK. Today's `BoardService.create_close_off_task`
   commits in two steps — `create_task()` inserts the row, then
   `update_task()` stamps `close_off_worktree_id`
   (`src/board/services.py:471-486`). Both calls commit
   independently (`src/board/repository.py:242-279`). A naive
   catch-`IntegrityError` → re-read on the second commit therefore
   leaves the loser's task row persisted with `close_off_worktree_id
   = NULL` — an orphan that pollutes the board and breaks the
   spec's idempotency claim.

   **Required refactor for T-434:** change
   `BoardService.create_close_off_task` to insert the task with
   `close_off_worktree_id` set in the *initial* INSERT (single
   commit), so the unique-index violation aborts the whole row
   instead of just the FK update. With that in place, the loser's
   pattern becomes: catch `IntegrityError` → rollback (a single
   uncommitted row, cleanly discarded) → re-read with
   `find_close_off_task` → return the existing row. Pin obligation
   #6 carries this requirement. Both the route-layer trigger and
   the backfill command then benefit from one fix in one place.

   The smaller alternative — quiesce live registrations during
   backfill — remains acceptable for cloglog (single-host,
   operator-driven `make backfill-close-off`) and **must** be
   documented in the command's `--help` if T-433 picks it instead
   of the refactor.

2. **Stale / closed / force-unregistered worktrees with no close-off
   row.** Leave alone. There is no useful teardown work to track on a
   worktree that is already gone; filing a backlog card for it would
   pollute the board with rows the supervisor cannot meaningfully
   action.

The backfill command has no rollback semantics — backfilled rows
are real teardown work that operators may legitimately complete, so
"undoing" the backfill would discard live state. The CLI flag layout
intentionally has no `--rollback` / `--undo` option; reverting the
T-434 PR ships the schema/contract change back without touching the
filed close-off rows.

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

The original draft of this section made close-off creation
best-effort. Codex round 4 correctly rejected that: T-378 hardened
`.cloglog/on-worktree-create.sh` to fail loud on any close-off
creation error precisely because the warn-and-continue path masked a
real-world incident on 2026-04-24
(`.cloglog/on-worktree-create.sh:88, 168-190`;
`tests/plugins/test_on_worktree_create_fails_loud.py:6`). Downstream
consumers — close-wave's Step 1.5 (`close-wave/SKILL.md:87`) and the
supervisor's `setup` skill that hands directly off to close-wave when
no backlog tasks remain (`setup/SKILL.md:104`) — still treat a
missing close-off row as a hard failure. Best-effort here would
silently regress the same fail-loud contract.

**Revised rule:** first-time close-off creation for a `role='worktree'`
registration is a **hard gate**. If the row cannot be created, the
HTTP `register_agent` call returns 5xx (or whatever status the
existing `routes.py` close-off path uses on failure — match it
exactly), the supervisor's launch flow surfaces the error the same
way the on-worktree-create.sh POST does today, and the worktree
agent does not proceed to start work.

Within that gate the per-error handling is:

- **`IntegrityError` on `uq_tasks_close_off_worktree_id`** (the
  migration / re-entrant register race): catch, rollback the
  close-off insert, re-read with
  `find_close_off_task(close_off_worktree_id)`, return the existing
  row. This is a **clean idempotent hit**, not a failure — the
  row exists, so the gate passes.
- **All other failures** (transient DB error, FK violation, schema
  bug, missing main-agent resolver, etc.): the route returns 5xx and
  the worktree registration must not be visible as "online" to other
  consumers. **The current `AgentService.register` flow does not
  support a clean rollback** — `services.py:133-212` commits the
  worktree row, token hash, session row, and `WORKTREE_ONLINE` event
  along the way (`repository.py:23-65, 135-163, 218-226` show each
  step commits independently). T-434 therefore must restructure the
  route so first-time close-off creation runs **before** the
  registration's commits and emitted events — concretely, the route
  opens one session, calls a refactored `AgentService.register` that
  defers commit/event emission, then calls
  `BoardService.create_close_off_task` on the same session, and only
  commits + publishes `WORKTREE_ONLINE` once both succeed.
  Alternative shape — wrap both calls in an outer SAVEPOINT so a
  failure in close-off creation rolls back to before the `register`
  state is visible. T-433 picks one. Either way, the spec is clear:
  do **not** ship a route that calls `register` then `create` then
  tries to "undo" a committed registration; the codebase does not
  support that.

  Until that refactor lands, the `register_agent` route MUST NOT
  emit a `WORKTREE_ONLINE` event before the close-off gate passes —
  the event is the load-bearing signal supervisors and dashboards
  consume, and a partial registration that emits ONLINE then 5xxs
  is worse than no rollback at all.
- **Resume / re-register** (worktree row already exists): the route
  short-circuits via the existing
  `worktree_id` lookup; `find_close_off_task` returns the existing
  row; gate passes idempotently. No regression here — the gate only
  fails when a brand-new `role='worktree'` row could not get its
  close-off card on first creation.

This matches the on-worktree-create.sh behaviour exactly, so swapping
the per-project POST for the backend trigger is a pure refactor of
*where* the gate lives, not a downgrade of the contract.

Reconcile (T-371) remains the self-heal path for any orphan/missing
row that slips through after the fact (manual DB edits, partial
recovery, etc.) — but it is **not** the primary correctness mechanism
for the happy launch path, which is what the prior draft incorrectly
implied.

## In scope (T-434), expanded by codex round 2

The schema additions (`close_off_worktree_id` on `TaskCard` /
`TaskResponse`) and the close-wave / reconcile predicate updates
land in the same T-434 PR as the backend trigger and migration.
They are non-negotiable: without them the force-unregister edge
case produces ambiguous title matches that close-wave's Step 1.5
cannot disambiguate. T-433 (plan) must order these edits before the
migration so the consumer contract ships before any new orphan
cards can be produced.

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
5. First-time close-off-task creation failure (any error other than
   the idempotent re-read on a unique-index hit) **does** fail the
   `register_agent` call. Matches the `.cloglog/on-worktree-create.sh`
   fail-loud contract from T-378 and prevents the 2026-04-24
   missing-close-off incident from regressing through a different
   path.
6. The migration/race `IntegrityError` path returns the existing row
   AND does not leak an orphan task row from the loser's partial
   commits. T-434 must refactor `BoardService.create_close_off_task`
   to insert the task with `close_off_worktree_id` set in the
   initial INSERT (no follow-up `update_task` for the FK) so the
   unique-index violation aborts the whole row, not just the FK
   stamp.
7. The backfill command (a) is idempotent on the natural key, (b)
   fails fast when no main agent resolves so it cannot file
   unassigned rows that the existing service path will never
   repair, and (c) `BoardService.create_close_off_task` backfills
   `worktree_id` on a previously-unassigned existing row when the
   resolver now succeeds, preserving the visibility contract pinned
   by `tests/agent/test_close_off_task.py:521-565` across both
   live-trigger and manual MCP re-calls.
8. `TaskCard` and `TaskResponse` (`src/board/schemas.py`) expose
   `close_off_worktree_id: Optional[UUID]`; round-trip pinned in
   `tests/board/test_schemas.py`.
9. Close-wave Step 1.5 lookup keys on
   `close_off_worktree_id == worktree.id` (with title equality as a
   defensive sanity check) so a re-registered worktree with a stale
   orphan card does not produce an ambiguous match. Reconcile's
   close-wave-delegation component gets the same predicate update.
10. The migration filters source rows by
    `worktrees.status = 'online' AND worktrees.role = 'worktree'`
    so offline (heartbeat-timed-out) rows AND `role='main'`
    registrations are both excluded from the backfill.
11. Calling `register_agent` from the main checkout (`role='main'`)
    does NOT file a close-off card. Pinned at the trigger level so a
    future refactor cannot regress the carve-out.
12. Close-wave Step 1 calls `mcp__cloglog__list_worktrees()` before
    the board lookup and builds `wt-name → worktree_id` so Step 1.5's
    FK-based predicate has the UUID it needs. Reconcile's
    close-wave-delegation component already does this; pin keeps
    close-wave aligned.
13. The backfill ships as an application-level command
    (`make backfill-close-off` or equivalent) that opens an
    `AsyncSession` and reuses `BoardService.create_close_off_task`,
    NOT as an Alembic data migration. Pin guards against a future
    refactor that tries to inline the row-creation logic in sync
    SQL inside `upgrade()` and silently regresses numbering /
    rollup invariants.
14. The route-layer `register_agent` handler — not
    `AgentService.register` — calls
    `BoardService.create_close_off_task`. Pin keeps the
    cross-context orchestration at the documented composition
    boundary and prevents `AgentService` from growing a direct
    `BoardService` dependency.
15. First-time close-off creation for a `role='worktree'`
    registration is a **hard gate**. If the row cannot be created
    (any error other than the idempotent `IntegrityError` re-read),
    the HTTP `register_agent` call fails. Pin guards against a
    future refactor that re-introduces best-effort behaviour and
    silently regresses the T-378 fail-loud contract.
16. The route does NOT emit `WORKTREE_ONLINE` (or any other
    event-bus signal that consumers treat as "agent live") before
    the close-off gate passes. Pin via an integration test that
    asserts a forced close-off failure on first registration
    leaves no `WORKTREE_ONLINE` on the bus and no committed
    worktree row visible through `get_active_tasks` /
    `list_worktrees`.
17. `BoardService.create_close_off_task` inserts the task with
    `close_off_worktree_id` set in the initial INSERT so an
    `IntegrityError` aborts the whole row, not a leftover task with
    NULL FK. Pin via a concurrent-call test that asserts exactly
    one task row exists for the contended worktree after the race.
18. The backfill command fails fast when no main agent resolves.
    Pin via a CLI test that runs the command against a project
    with no `role='main'` worktree and asserts non-zero exit + no
    rows filed.
