# Wave: t371-pr-task-blocker — work log

Date: 2026-05-02
Worktrees: `wt-t371-pr-task-blocker`
PRs: #287

## Worktrees in this wave

### wt-t371-pr-task-blocker

- **PR:** [#287 — feat(t-371): block gh pr create without board task; wire close-wave through lifecycle](https://github.com/sachinkundu/cloglog/pull/287) — merged 2026-05-02T10:26:48Z
- **Branch:** `wt-t371-pr-task-blocker` (base `origin/main` @ d23a5df)
- **Commits:** 6 (1 feat + 5 codex review fix-ups)

```
0b2ed6c fix(t-371): codex review round 5 — clear state.json in main-repo SessionEnd branch too
feb83fa fix(t-371): codex review round 4 — resolve worktree root in agent-shutdown.sh
aa3e6fd fix(t-371): codex review round 3 — narrow done claim, use start_task in reconcile
3ff316f fix(t-371): codex review round 2 — chmod state.json, fix reconcile pr_url recovery
3e58f72 fix(t-371): codex review — gitignore state.json + clear it on SessionEnd
ddd64b5 feat(t-371): hard-block gh pr create without an in_progress board task + wire close-wave through the lifecycle
```

- **Files changed:**
  - `.gitignore`
  - `docs/demos/wt-t371-pr-task-blocker/exemption.md`
  - `mcp-server/src/client.ts`, `mcp-server/src/server.ts`, `mcp-server/src/state.ts` (new)
  - `mcp-server/tests/server.test.ts`, `mcp-server/tests/state.test.ts` (new)
  - `plugins/cloglog/hooks/agent-shutdown.sh`
  - `plugins/cloglog/hooks/require-task-for-pr.sh`
  - `plugins/cloglog/skills/close-wave/SKILL.md`
  - `plugins/cloglog/skills/reconcile/SKILL.md`
  - `tests/plugins/test_close_wave_skill_lifecycle_calls.py`, `tests/plugins/test_require_task_for_pr_blocks.py` (new)

#### Per-task work log (T-371) — from `work-log-T-371.md`

```
---
task: T-371
task_type: impl
title: "Block gh pr create without an in_progress board task + wire close-wave through the lifecycle"
feature: F-50
worktree: wt-t371-pr-task-blocker
pr: https://github.com/sachinkundu/cloglog/pull/287
pr_number: 287
merged: true
codex_rounds: 5
final_state: merged_after_5_codex_rounds_human_review
---
```

##### Summary

Closed two long-standing gaps: `gh pr create` was advisory-only (no board task linkage was actually required to ship a PR), and close-wave runs never moved their own `Close worktree wt-<X>` rows out of backlog. Result before T-371: 7 stale close-off rows on F-50 (T-355, T-357, T-359, T-361, T-364, T-366, T-369) for waves whose PRs had already merged. After T-371: every `gh pr create` that bypasses the board is hard-blocked with exit 2, every close-wave PR carries its own close-off task lifecycle, and reconcile has an auto-fix rule for any future stragglers.

##### Files touched (annotated)

- `mcp-server/src/state.ts` (new) — helper around mkdir/writeFile/unlink with 0o600 perms + unconditional chmod on every write.
- `mcp-server/src/server.ts` — register_agent persists `<worktree>/.cloglog/state.json`; unregister_agent removes it.
- `mcp-server/src/client.ts` — `getBaseUrl()` accessor so server.ts can persist the backend URL without re-importing config.
- `plugins/cloglog/hooks/require-task-for-pr.sh` — full rewrite: walks `$CLAUDE_PROJECT_DIR` (or `$PWD` upward) to find state.json, queries `GET /api/v1/agents/{worktree_id}/tasks` with the agent token, exit 2 with actionable messages for every failure mode.
- `plugins/cloglog/hooks/agent-shutdown.sh` — clears state.json on SessionEnd in BOTH the worktree branch and the main-repo branch, using `WORKTREE_ROOT` / `MAIN_ROOT` resolved via `git rev-parse --show-toplevel`.
- `.gitignore` — added `.cloglog/state.json`.
- `plugins/cloglog/skills/close-wave/SKILL.md` — Step 1 resolves close-off task UUIDs into `close_off_task_ids` / `PRIMARY_CLOSE_TASK_ID`; new Step 9.7 calls `start_task` before branch creation; new Step 13.5 moves every close-off task in the wave to `review` with `pr_url` after `gh pr create`. Documents the user-only-done terminal state.
- `plugins/cloglog/skills/reconcile/SKILL.md` — new "Stale close-off tasks" subsection. Recovery uses `gh pr list --state merged --search "in:title chore(close-wave)"` filtering by body content, not the broken `git log --grep "wt-close-.*${wt_X}"` recipe; revival uses `start_task` (one-active-task guard) not `update_task_status(..., "in_progress")`.

##### Tests added

- `tests/plugins/test_require_task_for_pr_blocks.py` — 8 cases.
- `tests/plugins/test_close_wave_skill_lifecycle_calls.py` — 3 cases.
- `mcp-server/tests/state.test.ts` — 6 cases on the helper.
- `mcp-server/tests/server.test.ts` (+2) — register_agent writes / unregister_agent removes state.json; absent agent_token writes nothing.

##### Codex review history (5 rounds)

1. **HIGH** — state.json not gitignored.
2. **CRITICAL** — agent-shutdown.sh didn't clear state.json.
3. **HIGH** — `writeFile`'s `mode: 0o600` only applies on create.
4. **HIGH** — reconcile pr_url recovery used the wrong branch invariant (`wt-close-.*${wt_X}` matches reconcile-delegated waves only).
5. **MEDIUM** — close-wave claimed "no manual operator step" but agents can't move tasks to done.
6. **HIGH** — reconcile stale-close-off revival used `update_task_status(..., "in_progress")` which bypasses start_task's one-active-task guard.
7. **MEDIUM** — agent-shutdown.sh's worktree-branch rm used `$CWD` which can be a nested subdir.
8. **MEDIUM** — agent-shutdown.sh's main-repo branch (GIT_DIR == GIT_COMMON) didn't rm state.json at all.

After session 5 the bot exhausted its 5-round budget without approving; the human reviewer merged.

##### Residual TODOs (carried forward)

- Narrowed acceptance — close-off rows terminate at `review + pr_merged=True`, user drags to done — diverges from the original task.md framing. End-to-end automation of close-off teardown requires a backend hook on `pr_merged` for tasks with a `close_off_worktree_id`-shape marker, bypassing user-only-done for that one task type. Deliberately deferred.
- Hook degrades to "backend unreachable, refusing to create PR" when `make dev` is down. Intended fail-loud shape; if operators find this disruptive in practice, consider a `CLOGLOG_HOOK_FAIL_OPEN=1` env override (do not remove the block silently).
- 7 pre-existing stale rows (T-355…T-369) were cleaned up by the operator before T-371 landed; new reconcile rule exists to prevent re-accumulation.
- `mcp-server/dist/` is rebuilt by `make sync-mcp-dist` (close-wave Step 9.5) — `state.ts` ships in the bundle from this wave forward.

## Shutdown summary

| Worktree | PR | Shutdown path | Notes |
|---|---|---|---|
| wt-t371-pr-task-blocker | #287 | cooperative | Agent self-unregistered via pr_merged inbox event. Launcher + claude lingered after `unregister_agent` (T-352 in flight); supervisor closed the zellij tab to clean up — Step 6 surface. |

## Learnings & Issues

### What was tested

`make quality` on the close-wave branch (`wt-close-2026-05-02-wave-t371-pr-task-blocker`) before PR creation — see Test Report below.

### Operator-side bootstrap notes for the new hook

This is the first close-wave run after T-371's hook went live. Two operator-side rough edges surfaced:

1. **Pre-existing supervisor sessions have no `state.json`.** The hook reads it; without it, `gh pr create` is blocked. The supervisor that ran this close-wave was started before T-371 shipped, so its MCP session bound the old `register_agent` (which didn't write state.json). Workaround used: hand-write `.cloglog/state.json` from the values returned by the most recent `register_agent` call (worktree_id, agent_token, backend_url=`http://127.0.0.1:8001`). The next supervisor restart will pick up the new MCP bundle and write state.json natively, so this is one-shot. Logged so the next close-wave operator doesn't burn 10 minutes diagnosing a 401.
2. **Agent token rotates on resume.** When `register_agent` is called against a resumed worktree, the gateway issues a fresh `agent_token` and the prior one becomes invalid. If you wrote state.json from an earlier register call, you must rewrite it after every re-register — otherwise the hook's `Authorization: Bearer …` query gets `401 Invalid agent token`. Future improvement: have the hook treat 401 as "stale token, re-register required" with a specific message instead of the generic "unexpected response" path.

### What's now in place

- Every `gh pr create` from a registered worktree is gated on at least one in_progress task. No path to a PR without board linkage.
- close-wave SKILL Step 9.7 calls `start_task` on the close-off task and Step 13.5 moves it to `review` with `pr_url` after PR open. The webhook fan-out marks `pr_merged=True` on merge; user drags to done.
- reconcile SKILL has a "Stale close-off tasks" rule that auto-fixes any pre-existing dangling rows by matching the title against merged `chore(close-wave): wave-…` PR bodies.

## State After This Wave

- F-50 has T-339 (close-tab focus bug, expedite) and T-305 (webhook routing miss) remaining as the two distinct, non-redundant relevant tasks. T-371 closed.
- T-372 (`Close worktree wt-t371-pr-task-blocker`) moves through `in_progress → review → done` as part of THIS PR — the first end-to-end exercise of the new lifecycle.
- 7 historical stale close-off rows (T-355…T-369) deleted earlier in the session by the operator; counted as cleanup, not regression-bait.
