# Work log — wt-t428-exit-on-unregister

Closed: 2026-05-05.
Wave name: t428-exit-on-unregister (single-task wave).

## Worktrees

| Worktree | Branch | Tasks | PR | Shutdown path |
|----------|--------|-------|----|---------------|
| wt-t428-exit-on-unregister | wt-t428-exit-on-unregister | T-428 | [#327](https://github.com/sachinkundu/cloglog/pull/327) | cooperative + tab-close cleanup (recurrence #6 — last one with old hook code) |

## What shipped (from `work-log-T-428.md`)

The hook was firing all along — supervisor's earlier diagnosis ("no trap entry in debug log") was wrong because it grep'd for the launch.sh signal trap line, not the `exit-on-unregister.sh scheduled TERM claude_pid=...` line the hook itself writes. Two real failure modes, addressed together:

1. **`$PPID` did not point at claude reliably.** Depending on whether claude spawns hooks via `sh -c`, `bash -c`, or direct exec, `$PPID` could be a transient wrapper shell that exited before the kill landed, leaving claude orphaned and alive.
2. **Claude's Node process trapped TERM with cleanup logic that did not exit.** A single `kill -TERM` is insufficient against a process that handles TERM as "begin cleanup, stay alive."

### Fix

- `plugins/cloglog/templates/launch.sh.template` — write `<worktree>/.cloglog/claude.pid` immediately after backgrounding claude; cleanup on EXIT.
- `plugins/cloglog/hooks/exit-on-unregister.sh` — read `claude.pid` first (preferred), fall back to `$PPID` for back-compat with worktrees launched before the fix. Escalate `TERM → 4s → INT → 4s → KILL`. Log every step with a `pid_source=pidfile|ppid` field so future triage can tell which path took effect.
- `tests/test_exit_on_unregister_hook.py` — 4 new pin tests:
  - `test_parent_trapping_term_is_escalated_to_kill` — pins the escalation path.
  - `test_parent_trapping_term_only_dies_on_int` — pins the INT-stage of the escalation.
  - `test_hook_prefers_pidfile_over_ppid` — pins the pid-source priority.
  - `test_launch_template_writes_pidfile` — pins the template change.
  - Original 5 tests still pass via `$PPID` back-compat fallback.
- `.gitignore` — `.cloglog/claude.pid` is runtime-only.

PR #327 merged 2026-05-05T08:22:30Z. Codex `:pass:` first session.

## Shutdown summary

This worktree's own teardown was recurrence #6 of the bug it was fixing — expected, because the running claude session loaded its hook configuration at startup, well before the fix landed. The fix only takes effect on **fresh launches** post-merge.

## Decisions worth highlighting

- **PID-file preferred, `$PPID` fallback retained.** Workrees launched before this PR do not have `claude.pid` files; the fallback keeps them shutting down (less reliably, but at least logging) until they've been re-launched against the new template. Once every active worktree has cycled through, the fallback can be removed; not urgent.
- **Escalation timeline 0s + 2s + 4s + 4s = 10s max.** Tightening below ~2s before TERM risks racing claude's MCP tool-response transit (the unregister response is in flight when the hook fires).
- **No changes to `agent-shutdown.sh` (SessionEnd) or `launch.sh`'s signal trap.** Those are complementary backstops for different shutdown paths (claude exits without `unregister_agent`; operator force-closes the tab). Don't conflate them with the unregister-driven path this PR fixes.

## State after this wave

- T-428 SHIPPED. **Recurrence count this session: 6.** All under old hook code.
- The next launched worktree will be the first real-world test of the new escalation path. If its post-merge teardown shows `pgrep` empty within 5s of `agent_unregistered` and the debug log carries `pid_source=pidfile` lines, the fix is verified end-to-end.
- E-10 / agent-lifecycle hardening can now proceed without the manual tab-close workaround. F-57 (backend close-off) and F-58 (templating sweep T-435) are next-up.

## Investigator notes

- The `pid_source=pidfile|ppid` field in `/tmp/agent-shutdown-debug.log` distinguishes which path the hook took. Use it during the next recurrence triage instead of guessing.
- The original task description's "no trap entry" claim was wrong — it conflated launch.sh's signal trap log with the hook's own log. Future debugging of the agent-lifecycle area should grep both `launch.sh trap fired` AND `exit-on-unregister.sh` patterns separately.
