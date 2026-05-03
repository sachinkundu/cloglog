# Wave: Launcher + Zellij Cleanup (T-352, T-384) — 2026-05-03

Two-task wave on a single worktree (`wt-launcher-zellij-cleanup`). T-352 shipped first, the worktree was reset to `origin/main` to pick up the new hook, then T-384 ran on the refreshed checkout.

## Worktrees in this wave

| Worktree | Branch | PRs | Tasks | Shutdown path |
|---|---|---|---|---|
| `wt-launcher-zellij-cleanup` | `wt-launcher-zellij-cleanup` | [#298](https://github.com/sachinkundu/cloglog/pull/298) (T-352), [#301](https://github.com/sachinkundu/cloglog/pull/301) (T-384) | T-352 → T-384 | tier-1 (`agent_unregistered` received both times); manual `close-zellij-tab.sh` after each because plugin cache is frozen — T-352's hook never reaches running agents (T-387) |

## Shutdown summary

- **T-352 / PR #298** — agent unregistered cleanly 2026-05-03T07:55:35. Launcher lingered (T-352's own bug — fix in this PR but cache-frozen, see Learnings). Tab closed via helper.
- **T-384 / PR #301** — same worktree, relaunched after `git reset --hard origin/main`. Agent unregistered cleanly 2026-05-03T08:13:50. Launcher STILL lingered despite T-352 hook being in the worktree's `plugins/cloglog/` — T-387 explains why: claude reads from the cache copy at `~/.claude/plugins/cache/cloglog-dev/cloglog/0.1.0/`, frozen at 2026-04-13. Tab closed via helper again.

## What shipped (per-task work logs verbatim)

### T-352 (PR #298) — from `shutdown-artifacts/work-log-T-352.md`

**Goal.** After agent emits `agent_unregistered` and calls `unregister_agent`, claude continues running interactively waiting for the next user input — keeping the launcher's `wait` blocked. Supervisor was forced to close the zellij tab to recover. Fix the agent-side exit so the launcher returns naturally.

**What shipped.** PostToolUse hook on `mcp__cloglog__unregister_agent` (`plugins/cloglog/hooks/exit-on-unregister.sh`) that schedules SIGTERM to the parent claude PID after a successful unregister. Hook fires only on success (matches `Unregistered ` text prefix in the response, refuses if `isError`/`is_error` is true) so failed unregisters still flow through the existing `mcp_tool_error` escalation path in `agent-lifecycle.md` §4.1. Wired in `plugins/cloglog/settings.json`. Six pin tests in `tests/test_exit_on_unregister_hook.py`. Close-wave SKILL Step 6 prose downgraded from "rare, but possible" to a one-line note that this hook should make it not happen.

### T-384 (PR #301) — from `shutdown-artifacts/work-log-T-384.md`

**Goal.** Two related fragilities: brittle `awk '/^id:/'` and `query-tab-names | grep` text parsing, and visible focus-steal between `new-tab` and `go-to-tab-by-id` when issued as separate commands.

**What shipped.**
- `plugins/cloglog/hooks/lib/close-zellij-tab.sh` rewritten to parse `zellij action list-tabs --json` via `jq`. Active-tab detection switched to JSON. Drops `query-tab-names | grep` and `current-tab-info | awk` entirely.
- `plugins/cloglog/skills/launch/SKILL.md` Step 4e: replaces `awk '/^id:/'` with `list-tabs --json | jq`; chains `new-tab` and `go-to-tab-by-id` in one `&&`-joined shell command so focus-back fires before the eye sees the swap. Same change in Supervisor Relaunch Flow.
- New pin `tests/plugins/test_zellij_list_tabs_json_contract.py` asserts the `list-tabs --json` shape (`tab_id` int, `name` str, `active` bool); skips when `zellij` not on PATH.
- `tests/plugins/test_close_zellij_tab_helper.py` extended with JSON-output fixtures.

## Learnings & integration issues

- **T-387 (filed expedite this wave).** The cloglog plugin is registered as a `directory`-source marketplace (`installLocation: /home/sachin/code/cloglog/plugins/cloglog`) but claude installs the plugin once by **copying** to `~/.claude/plugins/cache/cloglog-dev/cloglog/0.1.0/`. The cache `lastUpdated` was 2026-04-13. T-352's `exit-on-unregister.sh` lives in `plugins/cloglog/hooks/` (verified) but NOT in the cache `hooks/` directory; the cache settings.json has no `mcp__cloglog__unregister_agent` matcher. Result: T-352's fix shipped on main, present in every worktree's `plugins/cloglog/`, and never fires for any running claude session. Until T-387 lands, every plugin/hook/SKILL change has the same blind spot. **Manual `close-zellij-tab.sh` remains the load-bearing mitigation.**
- **`gh pr merge --delete-branch` worktree warning** reproduced again on PR #298 + #301 + #300. Documented in close-wave SKILL "Gotcha" — no new action.
- **The two PRs' impact would have caught this earlier with a cache-vs-source pin test.** Filed as part of T-387 acceptance.

## State after this wave

- `main` advanced from `3ac4523` to `9fbb7be` (combined T-352 + T-384 + close-wave PR #300).
- `exit-on-unregister.sh` in source tree but inactive due to T-387 cache-freeze.
- `close-zellij-tab.sh` and launch SKILL now parse `list-tabs --json` and use `&&`-chained focus-restore.
- `wt-codex-review-fixes` continues with T-375 in progress (T-376, T-381 queued). Same plugin-cache problem will hit it on next unregister — workaround: `close-zellij-tab.sh`.
- T-352 status: `review` with PR #298 merged.
- T-384 status: `review` with PR #301 merged.
- T-385 (close-off): in_progress; will move to `review` with this wave's PR.
