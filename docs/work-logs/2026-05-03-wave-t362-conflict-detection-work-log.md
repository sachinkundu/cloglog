# Wave: T-362 PR Conflict Detection (2026-05-03)

Single-worktree wave — `wt-t362-conflict-detection` ran T-362 in parallel with the launcher cleanup wave (`wt-launcher-zellij-cleanup` T-352→T-384).

## Worktrees in this wave

| Worktree | Branch | PR | Tasks | Shutdown path |
|---|---|---|---|---|
| `wt-t362-conflict-detection` | `wt-t362-conflict-detection` | [#299](https://github.com/sachinkundu/cloglog/pull/299) | T-362 | tier-1 (`agent_unregistered` received) + tab-close (T-352 hook absent — worktree predated the hook landing) |

## Shutdown summary

- **T-362 / PR #299** — agent emitted `agent_unregistered` cleanly at `2026-05-03T07:59:39+03:00`. Launcher + claude PIDs lingered post-unregister because this worktree was created **before** T-352 (PR #298) landed; the `exit-on-unregister.sh` PostToolUse hook isn't in this worktree's plugins/. Closed via `close-zellij-tab.sh wt-t362-conflict-detection` (rc=0). Future worktrees created after main was at ≥ `36c2c51` won't need the manual tab-close.
- **Close-off card**: T-386. The agent shipped a clean per-task work log and codex passed first try, so this is a smooth wave.

## What shipped (from `shutdown-artifacts/work-log-T-362.md`, T-362)

A **6th condition** on the worktree-agent's auto-merge gate that returns `pr_dirty` when `gh pr view --json mergeStateStatus` reports `DIRTY`. The `github-bot` SKILL's case statement now handles `pr_dirty` by moving the task back to `in_progress`, running `git fetch origin main && git merge origin/main`, resolving conflicts, and pushing — the resulting `synchronize` triggers a fresh codex review which re-runs the gate. AGENT_PROMPT.md documents the same flow.

### Files touched

- `plugins/cloglog/scripts/auto_merge_gate.py` — added `mergeable_state` field on `GateInputs`; new `pr_dirty` reason; `DIRTY_MERGE_STATE` constant; placed the check **before** `ci_not_green` so a dirty PR with pending CI doesn't deadlock on `gh pr checks --watch`.
- `plugins/cloglog/skills/github-bot/SKILL.md` — fetched `mergeStateStatus` (both initial gate payload and the post-CI re-evaluation payload); added 6th condition; added `pr_dirty` row to "When the gate holds" table; added `pr_dirty` case in case statement.
- `plugins/cloglog/templates/AGENT_PROMPT.md` — Step 10 references the `pr_dirty` resolve flow.
- `tests/test_auto_merge_gate.py` — added `mergeable_state="CLEAN"` default to `_inputs()` fixture; 7 new pin tests covering DIRTY, CLEAN, UNKNOWN, BLOCKED, empty, ordering vs ci_not_green, and CLI surface.
- `docs/demos/wt-t362-conflict-detection/exemption.md` — classifier exemption (plugin internals, no user-observable surface).

### Decisions (from agent's own log)

**Option 1 (gate-side check) over Option 2 (backend webhook fan-out).**

- GitHub does NOT fire a webhook on the affected PR when conflicts emerge from a sibling merge — only `opened`/`synchronize`/`closed` actions reach `parse_webhook_event` (`src/gateway/webhook.py:45-70`). The backend would have to either sweep open PRs on every `PR_MERGED` (requires GitHub API auth the backend currently does not have) or re-fetch on every `review_submitted` (still misses idle PRs).
- The agent's own `gh pr view` lookup at gate-evaluation time is the only signal that catches this case. The gate already runs `gh pr view` for labels — adding `mergeStateStatus` is one more JSON field, not a new API call.

**DIRTY check fires before `ci_not_green`.** A dirty PR with pending CI would otherwise deadlock on `gh pr checks --watch` waiting for a result that cannot help — GitHub has already disabled the merge button. Resolving the conflict + pushing restarts CI anyway, so paying the CI watch cost first is pure waste.

**`UNKNOWN` and empty `mergeable_state` are NOT held.** `UNKNOWN` is GitHub's transient state while it recomputes mergeability after a sibling merge; treating it as a hold would deadlock every PR for the seconds-to-minutes window after each sibling merge. Empty (older payload shape) keeps pre-T-362 callers working.

## Codex review

Codex passed on session 1/5 with no findings — verified the new condition is wired consistently into the helper, the documented agent workflow, and the pin tests; confirmed surrounding codepaths support the assumptions. No human reviews. Auto-merged on `:pass:` after CI completed (`ci`, `init-smoke`, `e2e-browser` all green).

## Residual TODOs / context for future tasks

- **Periodic poll while idle.** The current gate-side check covers the common case (codex usually reviews within 5-15 minutes, well after GitHub finishes recomputing mergeability for the sibling merge). If we observe production wedges where codex never returns AND mergeability flips to DIRTY mid-wait, file a follow-up to spawn a periodic Monitor that polls `gh pr view` while in `review`. Today, an idle PR whose codex review never fires would not detect DIRTY — `codex_review_timed_out` (T-374) covers the no-review-arrived case but does not check mergeability.
- **`gh pr merge --delete-branch` warns about worktree conflict.** When the gate auto-merged this PR, `gh pr merge --squash --delete-branch` printed `failed to run git: fatal: 'main' is already used by worktree at '/home/sachin/code/cloglog'` — but the merge itself succeeded on the remote. The local branch deletion failed because main is checked out in a sibling worktree. Cosmetic; remote branch deletion succeeded. Already documented in close-wave SKILL's "Gotcha" section.

## Learnings & integration issues

- **T-352 hook propagation gap.** Worktrees created before T-352 (PR #298) merged do not have `plugins/cloglog/hooks/exit-on-unregister.sh` and will linger on agent unregister. wt-t362-conflict-detection (created 2026-05-03 07:34, before T-352 merged 07:55) reproduced the linger; wt-codex-review-fixes (created 2026-05-02) will hit the same when T-375 ships. The supervisor's mitigation — close-zellij-tab.sh after agent_unregistered — works idempotently. The T-352 fix only takes effect for **new** worktrees. No follow-up task; the next wave that touches an old worktree should reset to origin/main before relaunch.

## State after this wave

- `main` advanced from `36c2c51` to `3cc6db6` (5 files, +189 / −8).
- Auto-merge gate now refuses to merge DIRTY PRs and routes them through the standard in_progress → fix → review flow.
- `wt-launcher-zellij-cleanup` worktree continues with T-384 in progress (T-352 already shipped this morning as PR #298).
- `wt-codex-review-fixes` continues with T-375 in progress (T-376, T-381 queued).
- T-362 status: `review` with PR merged; awaits user drag to `done`.
- T-386 (close-off): in_progress; will move to `review` with this wave's PR.
