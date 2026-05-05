# Wave: reconcile-wt-t475-exit-on-unregister-fix

**Date:** 2026-05-05
**Worktree:** wt-t475-exit-on-unregister-fix
**PR:** [#333](https://github.com/sachinkundu/cloglog/pull/333) — `fix(T-475): exit-on-unregister hook — breadcrumb + process-tree-walk fallback`
**Invoked from:** main agent salvage (worktree session crashed before commit; main agent committed + pushed + opened PR on the existing branch)

## Shutdown summary

| Worktree | Shutdown path | Commits | Notes |
|----------|----------------|---------|-------|
| wt-t475-exit-on-unregister-fix | salvage by main agent | 1 | Worktree session crashed mid-task. Working tree had complete, well-tested changes — main agent ran `force_unregister`, formatted one file via `ruff format`, ran `make quality` locally inside the worktree, committed, pushed via bot identity, opened PR #333. Codex `:pass:` session 1/5; auto-merge gate ran in main agent (CI watch + re-eval), squash-merged. |

## Commits

```
e8b8cbb fix(T-475): exit-on-unregister hook — breadcrumb + process-tree-walk fallback
```

## Files changed

- `plugins/cloglog/hooks/exit-on-unregister.sh` — three-strategy PID resolution (pidfile → process-tree walk → `$PPID`); unconditional breadcrumb log (overridable via `CLOGLOG_SHUTDOWN_LOG`)
- `tests/test_exit_on_unregister_hook.py` — 5 new pin tests (breadcrumb on early exit, breadcrumb on non-Unregistered response, tree-walk through wrapper shell, pidfile preferred over tree-walk, `$PPID` fallback)

## Synthesized work log

(No `shutdown-artifacts/work-log-T-475.md` was written — the worktree session crashed before reaching the per-task shutdown sequence. Reconstructed from the diff and PR body.)

### Root cause (2026-05-05 regression on wt-t430/t432/t435)

Those three worktrees had the older T-352 hook: no pidfile, just `$PPID`,
no debug log. `$PPID` was a transient wrapper shell spawned by Claude
Code; that wrapper exited before the `setsid` delay fired, so the kill
chain saw "parent already gone" and quit — claude stayed alive. The
absence of any `/tmp/agent-shutdown-debug.log` entries was the
diagnostic giveaway.

### Fix shape

Three-strategy PID resolution in priority order:

1. **T-428 pidfile** — read `<worktree>/.cloglog/claude.pid` (written by
   `launch.sh` after backgrounding claude). Reliable for any worktree
   created after T-428 shipped.
2. **T-475 tree walk** (new) — walk up to 5 levels of `$PPID` looking
   for a process whose argv contains `--dangerously-skip-permissions`.
   `launch.sh` always invokes claude with that flag; the hook is a child
   of claude through at most one or two shell wrappers. Hooks run
   synchronously, so the wrapper is alive during the walk.
3. **`$PPID` fallback** — last resort. Kept for back-compat; escalating
   TERM→INT→KILL still applies.

Plus an unconditional breadcrumb log line written the moment the hook
fires, before any early-exit guard, so investigators can distinguish
"hook never ran" from "hook ran but exited early." `CLOGLOG_SHUTDOWN_LOG`
env override added for testability.

### Codex review

Session 1/5: `:pass:`. Codex verified the hook against the surrounding
codebase (settings.json wiring, mcp-server unregister response shape,
launcher pidfile contract) and approved on first pass.

## Learnings & Issues

### Routing

- **Worktree-agent crash recovery — main agent salvage path.** The agent
  did the work (174 lines, 5 pin tests) but crashed before committing.
  Working tree was preserved by `git`; main agent committed + pushed +
  opened PR. This is the pattern for any future "agent crashed before PR"
  scenario: don't restart from scratch, salvage the working tree first.
  Not adding to a SKILL today — the path is rare and naming it would risk
  encouraging it.
- **Quality gate run inside the worktree before commit caught a `ruff`
  formatting violation** that would have failed CI. The salvage path
  must run `make quality` locally before pushing — the worktree's tests
  don't run in CI until after the push, so a missing format pass would
  bounce CI and add a round-trip.

### Quality gate
Passed on main after fast-forward (88.69% coverage maintained, 1481
backend tests).

## State after this wave

- `exit-on-unregister.sh` now reliably terminates claude on
  `unregister_agent` for both new (pidfile) and old (tree-walk)
  worktrees. The "should never happen" survival pattern observed on
  five 2026-05-05 worktrees should now be a real exception, not a
  recurring nuisance.
- Breadcrumb log path is now overridable for tests.
- T-475 remains in `review` on the board (user-only-done invariant);
  user moves to `done` when convenient.
