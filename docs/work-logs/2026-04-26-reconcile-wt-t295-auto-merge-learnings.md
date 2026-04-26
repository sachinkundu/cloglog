# Learnings — wt-t295-auto-merge

Patterns and gotchas worth carrying forward. Each entry is non-obvious and hit a real failure on this branch.

## "Eat your own dog food" surfaces real bugs static prose hides

Codex round 5 passed the implementation. Before declaring done, I tried to manually run the documented auto-merge bash against PR #224 itself. Two real bugs surfaced that no amount of static review caught:

1. **`gh pr view --jq ... --arg` crashes with `unknown flag: --arg`.** The `--arg` flag is only on `gh api` and standalone `jq`. `gh pr view` rejects it.
2. **`gh pr view --json statusCheckRollup` has no `bucket` field.** It returns `conclusion`/`status` enums in CheckRun shape. The normalized `bucket` (pass/pending/fail/cancel/skipping) only exists on `gh pr checks --json name,bucket`.

**Pattern:** if a skill documents an executable command sequence, run it end-to-end before merging. Static markdown review by anyone (including a careful reviewer like codex) misses runtime API quirks. Pin the executability with a doc-string regex test.

## Webhook bridge is narrower than it looks

`src/gateway/webhook_consumers.py:252` only emits `ci_failed` (success, null, neutral, skipped silently produce nothing). `src/gateway/webhook.py:45` only bridges `opened/synchronize/closed` `pull_request` actions — `labeled`/`unlabeled` are dropped.

**Implication for any future "the agent will react when X happens" design:** before claiming "the next webhook event re-runs this", check the consumer's filter set. Phrases like "wait for the next `check_run` webhook" are always wrong for the success path. The right escape hatch when the inbox can't trigger is a synchronous `gh pr checks --watch` inside the same handler invocation — that is one subprocess, not a `/loop`, and has a natural terminal state.

## CI workflow `paths:` filter ⇒ empty rollup on docs-only PRs

`.github/workflows/ci.yml` filters by `paths:` and excludes `docs/**`. A spec PR that touches only docs attaches zero check_runs. Any gate that treats "empty checks list" as "still pending" deadlocks those PRs forever — `gh pr checks --watch` returns immediately with no rollup, and the agent has nothing to wait for.

**Rule of thumb:** for any PR-state predicate over CI checks, decide what "no checks" means up front. The semantically right answer for an auto-merge gate is "no CI signal to wait for ⇒ green" (codex still ran; spec PRs are docs-only by intent). Accept the small trade-off that the post-push pre-enqueue window is also empty; in practice codex review takes long enough that CI has always enqueued by then.

## Codex `event="COMMENT"` means GitHub never sees it as approval

`post_review` in `src/gateway/review_engine.py` always pins `event="COMMENT"`. Codex's `:pass:` is a body marker, not an approval — GitHub still treats a separate human `CHANGES_REQUESTED` review as the merge-blocking authority. Any agent-side approval check that only inspects "did codex pass?" can run roughshod over a human's outstanding change request.

**Rule:** if your gate auto-merges, also fetch `gh api repos/.../pulls/<n>/reviews`, filter to non-bot users, group by login, take the latest review per author, and refuse the merge if any latest is `CHANGES_REQUESTED`. The user-block is the strongest hold and should fire before label/CI checks.

## Codex's 5-session cap is a hard ceiling

When the bot doesn't reach approval within 5 sessions it bails out and prints "Review skipped: ... Request human review." Any iterative back-and-forth that needs more rounds is on you to consolidate into earlier rounds or to escalate. After the cap, even a `:pass:` from a previous session no longer protects the latest SHA — the cap fires unconditionally on subsequent commits.

**Pattern:** in a multi-round review, prefer big consolidating fixes per round over small per-finding fixes. Each round is finite.

## Conflict resolution: 12-commit rebase ≫ 1-commit merge

When origin/main has moved and your branch has 10+ commits, a `git rebase origin/main` will surface conflicts at *every* replayed commit that touches a shared file. A `git merge origin/main` resolves the same conflicts once and produces a single merge commit. For long-lived feature branches that have already been reviewed, merge is the cheaper conflict-resolution shape.

(For a short clean linear history before first review, rebase is still the right call.)

## Worktree-scope discipline forces follow-up tasks for cross-context wiring

This worktree's scope was `plugins/cloglog/`, `docs/design/`, `tests/`. Codex round 3 flagged a real gap in `mcp-server/src/server.ts` (the `update_task_status` response message describing the pre-T-295 flow). The right move was to file a follow-up task (T-297) rather than break scope. Net: scope is honored, the gap is on the board, and the work is auditable.

**Pattern:** when a reviewer surfaces an out-of-scope finding, file a follow-up task on the relevant feature with concrete remediation steps, then say so explicitly in the reply. Don't silently expand scope.
