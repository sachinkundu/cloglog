# Wave: reconcile-wt-t419-inbox-monitor-dedup

**Date:** 2026-05-04
**Worktree:** wt-t419-inbox-monitor-dedup
**PR:** #321 (merged 2026-05-04 14:22:43 UTC)
**Branch:** wt-t419-inbox-monitor-dedup (deleted)
**Mode:** reconcile delegation (close-wave invoked from /cloglog reconcile)

## Shutdown summary

| Worktree | Path | Notes |
|---|---|---|
| wt-t419-inbox-monitor-dedup | manual TERM after orphan-launcher detected | Backend session already unregistered; per-task work logs were on disk but **lost** when the worktree was removed before consolidation (process error in this run — Step 5d should run before Step 7). Reconstructed from PR #321 body and commit list. Launcher PID 667804 + claude PID 667824 still alive — same orphan-launcher fingerprint as wt-t415 / wt-t416 today. Manual `kill -TERM 667804` cleared. Evidence appended to T-390. |

## Commits on `wt-t419-inbox-monitor-dedup`

```
1810742 fix(setup): T-419 process-level inbox monitor dedup to kill orphan tails
6f0e3cc fix(setup): T-419 detect legacy relative-path tail form via /proc cwd check
a2929f0 fix(setup): T-419 make non-Linux legacy-form scan cross-project safe
056bd33 fix(setup): T-419 Bash 3.2 compat + lsof cwd fallback for non-Linux legacy scan
a965744 fix(dedup): always kill all orphans and exit 2; remove exit-0 reuse path
cf7197b fix(dedup): canonicalize EXPECTED_CWD with pwd -P for symlinked checkouts
```

## Files changed

- `plugins/cloglog/skills/setup/dedup-inbox-monitor.sh` (new) — bash helper that scans for stale `tail -n 0 -F <inbox>` orphans via `ps -ww -eo pid=,args=` + awk, kills them all, exits 2 so the caller spawns fresh.
- `plugins/cloglog/skills/setup/SKILL.md` — Step 2 rewritten to call the helper, removed misleading TaskList framing.
- `tests/plugins/test_setup_skill_dedup.py` (new) — 10 pin tests covering the script + SKILL wiring + cross-project safety + zombie detection.

## Reconstructed per-task summary (from PR #321 body)

### Root cause

`setup/SKILL.md` Step 2 deduped via `TaskList`, scoped to the current Claude conversation's in-process task registry. After `/clear`, the conversation resets but the underlying `tail -n 0 -F` subprocesses keep running as orphans (the harness leaks them). The new session calls `TaskList`, sees zero matches, takes the "Zero → spawn fresh" branch, and adds another tail. N sessions → N tails → every inbox event fires N times.

### Fix

New helper `plugins/cloglog/skills/setup/dedup-inbox-monitor.sh`:

- Scans process table via `ps -ww -eo pid=,args=` and awk.
- Matches tail processes where `$2 ~ /\/tail$|^tail$/` (field 2 = `tail` binary, not a bash wrapper) AND `$NF == inbox` (last field = absolute inbox path, anchoring cross-project safety).
- **Final behavior** (after the design pivot in commit `a965744`): always kill all orphans, exit 2 → caller spawns a fresh Monitor bound to the current session's task registry. The earlier "keep the oldest, exit 0" branch was dropped because the kept orphan would have no `task_id` visible to the new conversation.
- Legacy-form fallback (commits `6f0e3cc`, `a2929f0`, `056bd33`): pre-fix invocations sometimes used the relative path `tail -f .cloglog/inbox`, so the script also reads `/proc/<pid>/cwd` (Linux) or `lsof -p <pid> -d cwd` (non-Linux) to identify those by working directory. Cross-project safe — only acts when the resolved cwd matches the target project root.
- `cf7197b` canonicalises `EXPECTED_CWD` via `pwd -P` so symlinked checkouts dedup correctly.

### Tests (10)

1. `test_script_exists_and_is_executable`
2. `test_skill_md_references_dedup_script`
3. `test_skill_md_does_not_instruct_calling_tasklist_for_dedup`
4. `test_no_tails_exits_2`
5. `test_one_orphan_is_killed_and_exits_2`
6. `test_one_orphan_kill_message_on_stderr`
7. `test_multiple_dupes_reduce_to_one`
8. `test_multiple_dupes_stderr_mentions_killed_count`
9. `test_cross_project_dedup_does_not_kill_other_inbox`
10. `test_cross_project_dedup_kills_only_target_inbox`

Spawns real `tail` subprocesses under `tmp_path`, runs the actual bash, asserts via `/proc/<pid>/status` (zombie-aware — `os.kill(pid, 0)` succeeds on zombies, so the State=Z exclusion matters).

### Residual TODOs / context

- **Tracking the kept orphan tail in the task registry** — moot in the final design (always kill + spawn fresh), but noted in case the policy reverts.
- **Cleanup of existing orphan tails on operator hosts** — one-shot: `pgrep -af "tail -n 0 -F .*/cloglog/inbox" | awk '{print $1}' | xargs kill`.

## Learnings & Issues

- **Process-error in this close-wave run.** Worktree was removed (Step 7) before the per-task work log files were inlined (Step 5d). The summary above is reconstructed from the PR body and commits, not the original `work-log-T-419.md`. The close-wave SKILL is explicit about ordering — supervisor needs to follow it. Filing a meta-fix is overkill, but the lesson is real.
- **Orphan-launcher regression (T-390) confirmed across all three of today's worktrees.** T-415, T-416, T-419 each needed manual TERM after `agent_unregistered`. With this fix landing, `/cloglog setup` no longer accumulates duplicate tails — but the launcher-not-exiting symptom is independent and still open.
- **Static-allowlist auto-exempt classifier path worked** — the entire diff lives under `plugins/*/skills/` and `tests/`, so `check-demo.sh` printed `Docs-only branch — no demo required.` No exemption file needed; classifier handled it. (Compare to T-415 which had a `chore(demo) ... add classifier exemption` commit because part of its diff touched `src/gateway/`.)

## State after this wave

- T-419 implementation merged in main (head — see `git log` for the wave-fold sha).
- `/cloglog setup` now always kills orphan tails and spawns one fresh monitor; duplicate-tail accumulation across `/clear` and across sessions is fixed.
- F-55 ("Supervisor inbox monitor lifecycle") has its first task done. Future tasks under F-55 can build on the helper script.
- All three worktrees from today's wave are torn down (T-416, T-415, T-419). Three close-wave commits land on `main` consecutively (T-416 / reconcile-T-415 / reconcile-T-419).
- Outstanding from today's session: T-390 (orphan-launcher) is the highest-leverage remaining work — three live recurrences in one day.
