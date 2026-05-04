# Wave: t370-inbox-monitor-hook

Single-task wave folding T-370 (Hook: enforce inbox monitor running after `gh pr create`).

## Worktree

| Worktree | Branch | PR | Shutdown path |
|----------|--------|----|---------------|
| wt-t370-inbox-monitor-hook | wt-t370-inbox-monitor-hook | [#315](https://github.com/sachinkundu/cloglog/pull/315) | cooperative + tab-close (T-390 recurrence: exit-on-unregister.sh did not fire for the worktree agent's claude PID despite firing for unrelated test runs ~1h earlier) |

## Per-task work log

### T-370 — PostToolUse hook enforcing inbox-monitor presence after `gh pr create` (`from work-log-T-370.md`)

#### What was built

`plugins/cloglog/hooks/enforce-inbox-monitor-after-pr.sh` (new, 121 lines) — a PostToolUse hook that blocks the agent's next action when `gh pr create` completes without an active inbox `Monitor` on the relevant `.cloglog/inbox`. Registered in `plugins/cloglog/settings.json` under `PostToolUse.Bash`. One-line note added to `plugins/cloglog/skills/github-bot/SKILL.md` rule #5. 18 pin tests in new `tests/plugins/test_enforce_inbox_monitor_hook.py`.

#### Codex review iterations (5/5 sessions)

- **Session 1 — MEDIUM + HIGH:** hook fired on failed/`--dry-run` `gh pr create`; gated on PR URL in `tool_response`. Stale exemption `diff_hash` (empty); recomputed.
- **Session 2 — HIGH:** the codex-fix commit invalidated the new hash; recomputed to `b416098...`.
- **Session 3 — HIGH:** legacy `tail -f .cloglog/inbox` (relative path, used by setup/github-bot crash-recovery) wasn't recognized; added second check using `[[:space:]]\.cloglog/inbox` regex.
- **Session 4 — HIGH:** relative-form check had no cross-repo guard. Switched to `ps -ww -eo pid=,args=` + `readlink -f /proc/<pid>/cwd` to verify the tail process's cwd matches the inbox owner's root.
- **Session 5 — MEDIUM:** in a worktree session, a legacy tail from the MAIN checkout (cwd=`PROJECT_ROOT`) was accepted despite tailing the wrong inbox. Computed `EXPECTED_MONITOR_CWD` as the inbox owner's root only — `PROJECT_ROOT` for main checkout, `WORKTREE_ROOT` for worktree session.

5/5 reached without `:pass:`; merged by human after all findings addressed.

#### Key design decisions

1. **Monitor detection via `ps -ww -eo pid=,args=` + `/proc/<pid>/cwd`** — no stable Claude Code internal state file for running monitors. Linux-specific with a non-Linux fallback.
2. **`EXPECTED_MONITOR_CWD` = inbox owner's root** — main checkout uses `PROJECT_ROOT`, worktree uses `WORKTREE_ROOT`. Prevents a supervisor monitor from satisfying a worktree agent's check.
3. **Two-check structure** — canonical absolute-path check (fast, covers new `Monitor` tool) + legacy relative-path check with `/proc` cwd guard.
4. **No silent auto-pass** — any inspection failure surfaces as warning + exit 2.

#### Residual TODOs / context the next task should know

- **Exemption-hash refresh friction** — codex flagged the stale `diff_hash` 4 times across 5 sessions because every code commit on the branch shifts the diff and invalidates the exemption. A pre-commit hook auto-refreshing the exemption hash would close this loop. Not filed as a task.
- **First Tier-3 enforcement** — this is the first behavioural/harness enforcement of an instruction-surface rule. Pattern works. Similar hooks could enforce `update_task_status to review after gh pr create` or other invariants.
- 18 pin tests, including integration-style ones that spawn real `tail` processes from a worktree cwd (`test_hook_passes_when_monitor_uses_legacy_relative_path`). Fast (< 1s total).

## Learnings & Issues

### Recurrence: exit-on-unregister.sh did not fire (T-390)

Third instance today. `/tmp/agent-shutdown-debug.log` shows the hook DID fire for unrelated test-driven claude PIDs (271493, 283157, 294544) ~1h earlier in the day, but did NOT fire for the actual worktree agent's claude PID at 12:48. The hook is registered and execrable but the PostToolUse trigger on `mcp__cloglog__unregister_agent` does not consistently reach the worktree-agent's session. T-390 already tracks investigation; recurrence noted.

### Quality gate

`make quality` on `main` after the merge passed.

### Routing

- T-390 recurrence: task-tracked.
- The Tier-3 enforcement pattern is now demonstrable; future hook authors can use this hook as a reference shape (cwd-aware, `/proc`-guarded, no silent-pass).
- No new silent-failure invariants — the hook is itself test-pinned.

## State After This Wave

- The `enforce-inbox-monitor-after-pr` hook is live in `plugins/cloglog/settings.json`. Future agents that open a PR without an inbox monitor will be blocked at the next action with an actionable message.
- Two parallel agents in flight: T-408 (PR #317 in_progress), T-409 (PR #318 just merged — close-wave queued).
