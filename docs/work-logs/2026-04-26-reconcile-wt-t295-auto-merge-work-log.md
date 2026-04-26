# Work log — wt-t295-auto-merge

**Task:** T-295 — Auto-merge on codex pass.
**PR:** [#224](https://github.com/sachinkundu/cloglog/pull/224) (merged).
**Worktree:** `/home/sachin/code/cloglog/.claude/worktrees/wt-t295-auto-merge`.
**Branch:** `wt-t295-auto-merge` (merged into `main`, deleted on remote).

## What shipped

A four-five-condition gate (`plugins/cloglog/scripts/auto_merge_gate.py`) that the worktree agent invokes after a `review_submitted` inbox event from `cloglog-codex-reviewer[bot]`. When all five hold — codex pass marker, no human `CHANGES_REQUESTED`, no `hold-merge` label, every CI check `pass`/`skipping` (or empty rollup, for docs-only PRs) — the agent runs `gh pr merge --squash --delete-branch` itself. The existing `pr_merged` webhook fires unchanged; main-agent close-off runs as before.

The gate is pure-Python so the truth table can be pinned in `tests/test_auto_merge_gate.py`. The github-bot, launch, and worktree-agent skill markdowns plus `docs/design/agent-lifecycle.md` §3.1 reference the helper rather than duplicating its logic.

## Timeline

1. **Round 0 (impl).** Drafted gate as 4-condition (codex reviewer + `:pass:` body + green CI + no `hold-merge` label). Pure helper + 15 truth-table tests + skill prose + design doc subsection.
2. **Round 1 (codex review).** Caught two issues:
   - MEDIUM: `ci_not_green` waited for a webhook that never fires (success/null/neutral/skipped don't reach the worktree inbox per `webhook_consumers.py:252`).
   - HIGH: `hold_label` claim that label removal re-triggers the gate was false (`webhook.py:45` only maps `opened/synchronize/closed`).
   - **Fix:** synchronous `gh pr checks --watch` for `ci_not_green`, document `hold_label` as human-action-required.
3. **Round 2 (codex review).**
   - MEDIUM: gate didn't defend against codex `:pass:` arriving after a human `CHANGES_REQUESTED` (codex always posts `event="COMMENT"`).
   - HIGH: design doc condition #3 still claimed CI-success webhook would re-trigger.
   - **Fix:** added fifth condition `has_human_changes_requested`, fetched from `gh api repos/.../pulls/<n>/reviews` filtered to non-bot users + grouped by login; rewrote design doc to point at the table.
4. **Round 3 (codex review).**
   - MEDIUM: empty CI rollup deadlocked docs-only spec PRs (CI workflow filters by `paths:`).
   - HIGH: `worktree-agent.md` still pointed at the pre-T-295 flow; `mcp-server/src/server.ts` did too.
   - **Fix:** flipped `_all_checks_green` to treat empty as green; updated `worktree-agent.md`; filed T-297 for the mcp-server message (out of scope for this worktree).
5. **Round 4 (codex review).**
   - HIGH: auto-merge bash referenced `${REPO}` before any `REPO=` derivation.
   - **Fix:** added the standard `REPO=$(...)` line at the top of the auto-merge snippet; pinned ordering with a regex test.
6. **Round 5 (codex `:pass:`, then self-test).** Codex passed; running the gate flow myself surfaced two more bugs the static prose missed:
   - `gh pr view --jq ... --arg` crashes with `unknown flag: --arg` (only `gh api` and standalone `jq` accept it).
   - `gh pr view --json statusCheckRollup` has no `bucket` field — that surface only exists on `gh pr checks --json name,bucket`.
   - **Fix:** sourced labels from `gh pr view --json labels`, checks from `gh pr checks --json name,bucket`, assembled with `jq -nc --argjson` for typed JSON injection. Re-ran end-to-end: `reason=merge rc=0`.
7. **Conflict resolution.** sachin asked for conflict resolution against origin/main (T-262 had landed). Both conflicts were in skill prose for the `pr_merged` handler — combined T-262's `pr_merged_notification` emission with this branch's auto-merge gate trigger so both fire on their respective events. Merged via merge commit (rebase would have replayed conflicts at every one of 12 commits).

## Test delta

`make quality`: 883 passed, 1 xfailed (was 872 at branch point).
- 18 new tests in `tests/test_auto_merge_gate.py` (5-condition truth table + ordering + CLI + missing-field defensives).
- 7 new doc-pin tests in `tests/plugins/test_auto_merge_skill_handles_silent_holds.py` covering: `--watch` invocation, `hold_label` human-action note, design-doc table, condition-3 anti-pin, `worktree-agent.md` references, REPO ordering, `gh pr checks --json name,bucket` source.

## Follow-ups

- **T-297** filed under F-48: extend the `update_task_status` MCP tool's CRITICAL response message in `mcp-server/src/server.ts` to mention the auto-merge gate. Out of this worktree's scope.

## Files touched

- `plugins/cloglog/scripts/auto_merge_gate.py` (new)
- `plugins/cloglog/skills/github-bot/SKILL.md`
- `plugins/cloglog/skills/launch/SKILL.md`
- `plugins/cloglog/agents/worktree-agent.md`
- `docs/design/agent-lifecycle.md`
- `tests/test_auto_merge_gate.py` (new)
- `tests/plugins/test_auto_merge_skill_handles_silent_holds.py` (new)
- `docs/demos/wt-t295-auto-merge/exemption.md` (classifier no_demo, internal plumbing)
