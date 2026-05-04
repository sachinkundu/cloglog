# Wave: t416-rollup-on-create

**Date:** 2026-05-04
**Worktree:** wt-t416-rollup-on-create
**PR:** #319 (merged 2026-05-04 13:12 UTC)
**Branch:** wt-t416-rollup-on-create (deleted)

## Shutdown summary

| Worktree | Path | Notes |
|---|---|---|
| wt-t416-rollup-on-create | manual TERM after orphan launcher detected | claude (PID 675761) and launcher (PID 675741) survived `agent_unregistered`. Step 6 of close-wave caught it; manual `kill -TERM 675741` cleared the tree without `kill -9`. T-390 amended with the new evidence. |

Cooperative shutdown was already triggered by the agent itself (received `agent_unregistered` event with `reason: pr_merged`); the regression was the post-unregister exit-on-unregister.sh failing to TERM claude. Same fingerprint as the original T-376 incident.

## Commits on `wt-t416-rollup-on-create`

```
281be5b feat(board): recompute feature/epic rollup on task creation (T-416)
eb37d64 chore(demo): classifier exemption for T-416 rollup-on-create
```

## Files changed

- `src/board/routes.py` — generic `create_task` route now goes through `service.create_task()` instead of `service._repo.create_task()` directly.
- `src/board/services.py` — new `BoardService.create_task()` centralises task creation, calls `recompute_rollup()` on the parent feature, and emits a `TASK_STATUS_CHANGED` SSE event when feature status flips. `create_close_off_task` and `import_plan` now use it too. `event_bus` imported into services.py.
- `tests/board/test_services.py` — two T-416 pin tests: (a) creating a task into a `done` feature flips it to `planned` / `in_progress` and emits SSE; (b) `create_close_off_task` and bulk `import_plan` paths trigger the same recompute.
- `docs/demos/wt-t416-rollup-on-create/exemption.md` — classifier exemption (no user-observable behaviour change).

## Inlined per-task work log (`work-log-T-416.md`)

### Summary

Fixed the silent rollup miss when creating a task into a done feature. Added `BoardService.create_task()` as a centralised task-creation method that wraps `_repo.create_task()` with a `recompute_rollup()` call and SSE event emission on status change. All three task-creation paths now go through it.

### Decisions

- Put event emission inside `BoardService.create_task()` (not in the route) so `create_close_off_task` and `import_plan` also get SSE fan-out.
- Imported `event_bus` into services.py — acceptable since the service already commits in-session; keeping the event emission co-located with the mutation is cleaner than leaking return values to callers.
- Used `TASK_STATUS_CHANGED` event type (same as status-update path) per the acceptance criteria. The `data` dict carries `task_id`, `old_status`, `new_status` (feature statuses) so the board UI re-renders correctly.
- `import_plan` bulk insert calls `self.create_task()` per task — fine since imported features are always brand-new (start at `planned`), so recompute is a near-no-op; consistency beats micro-optimisation here.

### Test evidence

Baseline 1423 → patched 1425 (2 new pin tests). Coverage 88.75%. Codex session 1/5 `:pass:`, no findings. CI green (ci + e2e-browser + init-smoke).

### Residual / context

- **Already actioned in this session:** the post-merge backfill the agent flagged (one-off rollup fix for features stuck at `done` with backlog tasks) was completed live — F-36, F-30, F-20, and the parent epic E-7 (`Automated Code Review`) were reopened earlier in the session before this PR even merged. F-29 was deliberately left at `done` per operator decision (its open task T-171 stays hidden).
- No follow-up tasks were filed from the implementation itself — the rollup state machine is unchanged; only call coverage was widened.

## Learnings & Issues

- **Orphan-launcher regression recurred (T-390).** `exit-on-unregister.sh` did not fire — debug log shows zero entries for the real T-416 unregister at 16:13:26. Whether the agent skipped `mcp__cloglog__unregister_agent` outright or the PostToolUse hook is misrouted is the open question. Evidence appended to T-390's notes; no new task filed.
- **Cross-project DB contamination** — earlier in the session, an audit `psql` against `cloglog_dev` returned features and tasks belonging to other projects sharing the same DB, because the SELECT did not filter by `project_id`. T-417 (hookify guard against direct psql) was filed in response.
- **MCP gap surfaced** — there is no single MCP tool that answers "done features with open tasks." `search` and `get_active_tasks` both filter done features out, which is why the audit reached for psql. A targeted tool (or a `search` flag) would close the gap.

## State after this wave

- T-416 implementation merged in main.
- Creating a task into a done feature now correctly bubbles the feature back to `planned` / `in_progress` and emits SSE.
- Task tree under F-36 (`PR Review Webhook Server`) and F-55 (`Supervisor inbox monitor lifecycle`) is now visible on the board.
- Two sibling agents still running: wt-t415-author-thread-replies (T-415, in review on PR #320), wt-t419-inbox-monitor-dedup (T-419, in review on PR #321). Their waves will fold separately when they merge.
- T-420 (spec for T-406 prod log monitor) sits backlog awaiting interactive launch.
