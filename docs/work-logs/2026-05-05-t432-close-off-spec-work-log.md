# Wave: T-432 close-off creation spec

**Date:** 2026-05-05
**Worktree:** wt-t432-close-off-spec
**PR:** [#329](https://github.com/sachinkundu/cloglog/pull/329) — `docs(spec): T-432 backend-owned close-off task creation`

## Shutdown summary

| Worktree | Shutdown path | Commits | Notes |
|----------|----------------|---------|-------|
| wt-t432-close-off-spec | cooperative (tier 1) | 6 | exit-on-unregister hook did NOT terminate the launcher; tab closed manually |

`request_shutdown` not issued — agent self-unregistered after PR merge
(`reason: pr_merged`). Cooperative artifact (`work-log-T-432.md`) consolidated
below.

## Commits

```
0b54edd docs(spec): T-432 address codex round 5 findings
32d2387 docs(spec): T-432 address codex round 4 findings
24552e4 docs(spec): T-432 address codex round 3 findings
79c396d docs(spec): T-432 address codex round 2 findings
8174c61 docs(spec): T-432 address codex round 1 findings
9b894e5 docs(spec): T-432 backend-owned close-off task creation spec
```

## Files changed

- `docs/design/backend-close-off-creation.md` (new, 484 lines after 5 codex rounds)

## Per-task work log (from `work-log-T-432.md`)

### Summary
Wrote `docs/design/backend-close-off-creation.md` — the spec gating T-433 (plan)
and T-434 (impl) for moving close-off-row creation from the per-project
`.cloglog/on-worktree-create.sh` POST into the backend's `register_agent` route.

### Decisions pinned
- **Trigger location:** route layer (`src/agent/routes.py::register_agent`),
  NOT `AgentService.register` — keeps `AgentService` free of a direct
  `BoardService` dep, mirrors the existing `/agents/close-off-task` route.
- **Role gate:** trigger + backfill apply only to `worktree.role == 'worktree'`;
  `role='main'` registrations from `/cloglog setup` skip close-off creation.
- **Idempotency:** natural key is `close_off_worktree_id`;
  `BoardService.create_close_off_task` already returns `(task, created)` with
  `created=False` on hits.
- **Force-unregister + re-register:** old worktree row is deleted; ON DELETE
  SET NULL clears the FK on the surviving close-off card. Re-register files a
  NEW card; orphan lingers with `close_off_worktree_id = NULL`.
- **Title contract:** `Close worktree <wt-name>` where `<wt-name>` is
  `worktree.branch_name or worktree.worktree_path.rsplit("/", 1)[-1]`.
- **Backfill:** application-level CLI (`make backfill-close-off`), NOT an
  Alembic data migration — preserves numbering + rollup invariants. Filters
  `status='online' AND role='worktree'`. Fails fast if no main agent resolves.
- **Concurrency:** T-434 must refactor `BoardService.create_close_off_task` to
  insert with `close_off_worktree_id` set in the initial INSERT (single
  commit) so an `IntegrityError` aborts the whole row.
- **Failure handling:** first-time close-off creation is a HARD GATE matching
  T-378 fail-loud. Route MUST NOT emit `WORKTREE_ONLINE` before the gate
  passes; T-434 either defers commits/events in `register` or wraps in an
  outer SAVEPOINT.
- **Schema additions:** `close_off_worktree_id` lands on `TaskCard` and
  `TaskResponse` so `get_board()` consumers (close-wave Step 1.5, reconcile)
  can key on the FK instead of title equality.
- **Close-wave Step 1 lift:** T-434 must move `mcp__cloglog__list_worktrees()`
  earlier so Step 1.5's FK predicate has the `wt-name → worktree_id` map.

### Pin obligations carried into T-433/T-434
18 pin tests enumerated in the spec's *Pins this spec carries* section.

### Codex review history
PR #329 went through all five codex review sessions; each round caught real
implementation hazards (force-unregister model mismatch, IntegrityError race,
`worktree.name` field nonexistent, migration assignee resolution, `TaskCard`
schema gap, status-online filter, failure-handling contradiction, `role='main'`
carve-out, Alembic sync-vs-async, close-wave Step 1 missing UUIDs, T-378
fail-loud collision, DDD boundary violation, migration numbering invariants,
route rollback after `register` commits, IntegrityError two-step commit leak,
pin self-contradiction, out-of-scope contradiction, unassigned-row repair).
Session 5/5 exhausted the 5-bot window — human merged.

## Learnings & Issues

### Bug: exit-on-unregister hook regression (T-428 follow-up)

**Symptom.** After `agent_unregistered` fired for `wt-t432-close-off-spec` at
13:06:33, the `bash launch.sh` (PID 2490935) and `claude --model
claude-opus-4-7` (PID 2490955) continued running for over 4 minutes. The same
condition was present for `wt-t430-skill-audit` immediately after its
unregister at 13:07:10.

**Expected.** Per `plugins/cloglog/skills/close-wave/SKILL.md` Step 6 and the
T-352 / T-428 design, the `exit-on-unregister` PostToolUse hook on
`mcp__cloglog__unregister_agent` schedules a TERM to claude on successful
unregister, so the launcher's `wait` returns naturally and `pgrep -f
"<worktree-path>"` returns nothing.

**Observed.** `/tmp/agent-shutdown-debug.log` had no entries for either worktree.
The hook either did not fire, did not target the right PID, or the TERM
delivery was lost. T-428 just shipped this work (`chore(close-wave):
t428-exit-on-unregister` on main as of 7ec97a9) so this is a fresh regression
or a not-fully-covered case.

**Workaround used.** `plugins/cloglog/hooks/lib/close-zellij-tab.sh
wt-t432-close-off-spec` cleaned up the tab; the launcher + claude died on
SIGHUP from tab closure. **Filed as T-475 under F-50.**

### Quality gate
Passed on main after fast-forward (`88.69%` coverage, 1479 passed, contract
clean, demo verified).

## State after this wave

- `docs/design/backend-close-off-creation.md` is the canonical spec gating
  the F-57 backend close-off-creation work.
- T-433 (plan) is next — must commit to: route-atomicity shape, concurrency
  mitigation, write the 18 pin tests.
- T-434 (impl) follows — sequence schema additions + close-wave Step 1.5
  predicate update before any new orphan cards can be produced.
- Both T-430 (skill audit) and T-435 (templating sweep) PRs are merged and
  awaiting their own close-wave folds.
