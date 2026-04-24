# Work log — reconcile-wt-t227-review-cap

Reconcile-mode close-wave delegation for `wt-t227-review-cap` after a clean
agent shutdown. Invoked from `/cloglog reconcile` Step 5.0 — the three
predicate components (shutdown-artifacts present, close-off task in backlog,
T-227 in review with `pr_merged=True`) all held.

- **Worktree:** `wt-t227-review-cap`
- **Path:** `/home/sachin/code/cloglog/.claude/worktrees/wt-t227-review-cap`
- **Branch:** `wt-t227-review-cap`
- **Task:** T-227 — Raise or replace MAX_REVIEWS_PER_PR cap (Option B with backstop=5)
- **PR:** [#201](https://github.com/sachinkundu/cloglog/pull/201) — merged 2026-04-24 04:38:59Z (commit `d0fd743`).
- **Agent unregistered:** 2026-04-24T07:41:13+03:00 (clean, `all_assigned_tasks_complete`).

## Commits

- `9ed59a7` feat(review): verdict-based stop + backstop=5 (T-227)
- `4f6e5f9` fix(review): scope approval check to current head_sha (T-227, codex round 1 MEDIUM)
- `3e79adc` fix(review): demote contradictory approve body (T-227, codex round 2 HIGH)

## Shutdown summary

| Worktree | PR | Shutdown path | Notes |
|----------|-----|----------------|-------|
| wt-t227-review-cap | #201 | cooperative (agent already unregistered before reconcile fired) | Tier-1 `request_shutdown` skipped — `list_worktrees` had no row for the agent's UUID; `agent_unregistered` was already in main inbox at 07:41:13. Teardown proceeded with artifact consolidation and `git worktree remove --force`. |

## What shipped (from worktree work-log.md)

`MAX_REVIEWS_PER_PR` raised from `2 → 5` and demoted from primary stop to
**safety backstop**. Primary stop is now verdict-based: if the latest codex
review for the **current `head_sha`** has the `:pass:` body prefix, skip
further review. Backstop fires only when the review loop hits 5 sessions
without an approval.

### Source — `src/gateway/review_engine.py`
- `MAX_REVIEWS_PER_PR: 2 → 5`.
- `_APPROVE_BODY_PREFIX: Final = ":pass:"` — canonical on-GitHub approval marker
  (codex bot pins `event="COMMENT"`, so GitHub's review state is never APPROVED).
- `_SEVERE_SEVERITIES: Final = frozenset({"critical", "high"})` — local mirror
  of `review_loop._SEVERE_SEVERITIES`; cross-referenced via comment so a
  future change to the severity set flags both files in review.
- `_format_review_body` — demotes `:pass:` → `:warning:` when
  `verdict == "approve"` AND any finding has severity in `_SEVERE_SEVERITIES`.
  Mirrors `ReviewLoop._reached_consensus` (PR #190 added that loop predicate
  after gemma4-e4b-32k emitted `:pass:` + `[CRITICAL]` in the same turn).
  Without this fix, the new T-227 approval helper would silently skip review
  on a contradictory body.
- `latest_codex_review_is_approval(repo, pr, token, head_sha, *, client=None) -> bool`
  — new async helper. Filters GitHub `/pulls/{N}/reviews` to codex-bot rows
  with `commit_id == head_sha`, then tests the `_APPROVE_BODY_PREFIX` on the
  latest matching row. Returns False on empty `head_sha` (short-circuits before
  HTTP) or when no codex review matches.
- `_should_skip_for_cap(prior, latest_is_approval) -> (skip, is_backstop)`
  — pure decision helper extracted for in-process demo and unit testability.
  Approval beats the backstop.
- `_review_pr` cap check rewritten: reads `head_sha` up-front, calls
  `count_bot_reviews`, short-circuits the approval helper when `prior == 0`
  (preserves zero-count test stubs), calls `_should_skip_for_cap`, branches
  to silent-skip or backstop-comment-skip.
- `count_bot_reviews` signature preserved per task constraint.

### Tests — `tests/gateway/test_review_engine.py`
- `TestShouldSkipForCap` (5 tests) — pure decision helper: four predicate cells
  + `MAX_REVIEWS_PER_PR == 5` pin.
- `TestLatestCodexReviewIsApproval` (8 tests) — including three regression
  tests: `test_approval_on_older_sha_does_not_apply_to_new_sha` (round 1
  MEDIUM guard), `test_returns_false_when_head_sha_is_empty`,
  `test_legacy_rows_without_commit_id_are_excluded`,
  `test_contradictory_approve_body_is_not_detected_as_approval`
  (round 2 HIGH full-path guard).
- `TestVerdictBasedCap` (3 integration tests) — proceed / silent-skip /
  backstop-with-comment end-to-end.
- `TestFormatReviewBody` extended with three demotion tests
  (critical/high demote, low/medium/info stay `:pass:`).
- `test_max_reviews_cap_posts_skip_comment` updated — stubs new helper +
  asserts new body wording (`maximum / 5 / approval`).

### Demo — `docs/demos/wt-t227-review-cap/`
Verify-safe: filesystem `grep -q` booleans + `uv run python -c` parse
round-trips. Six proof blocks covering the old-predicate-gone, new-predicate-
present, four-cell decision table, approval-prefix round-trip, contradictory-
demotion behaviour, and test-surface pins. No live-service `exec` blocks.

## Code review rounds

- **Round 1 (codex MEDIUM)** — `head_sha`-blind approval check would let an
  approval of commit A suppress review of a newly-pushed commit B. Fixed by
  adding the required `head_sha` argument and filtering rows by `commit_id`.
- **Round 2 (codex HIGH)** — `_format_review_body` still emitted `:pass:`
  for a contradictory verdict-vs-severity pair, fooling the new approval
  helper on webhook replay. Fixed by mirroring the loop's consensus
  predicate inside the body formatter.
- **Round 3** — pre-T-227 prod cap fired ("max of 2 sessions"); no review
  arrived for the demotion fix. The PR description had warned about this
  (prod runs pre-merge code on every PR). User reviewed and merged.

## CI flake (Board, not in scope)

`tests/board/test_routes.py::test_backlog_returns_tree` failed on CI run
24849583597 with non-deterministic task ordering (back-to-back creates can
collide on `Task.position`). Locally passed 5/5. Outside Gateway worktree
scope; left as a follow-up candidate. User re-ran CI and merged.

## Quality gate

Final run on PR #201 (post round 2 fix): lint clean, mypy 74 files, 812
backend tests + 1 xfailed, coverage 89.64% (≥ 80% floor), contract check
compliant, demo verified, MCP server build+tests passed.

Reconcile-mode close-wave does not re-run `make quality` on main — main was
green at merge time per CI; this is post-merge cleanup of an already-shipped
PR.

## State after this wave

- Local branch `wt-t227-review-cap` removed.
- Remote branch `origin/wt-t227-review-cap` removed via bot.
- Filesystem worktree `.claude/worktrees/wt-t227-review-cap` removed.
- Zellij tab `wt-t227-review-cap` closed.
- Close-off task **T-280** transitions through this reconcile's PR.

## Learnings folded into CLAUDE.md

1. GitHub body content is a side-channel — keep `_format_review_body`
   aligned with `ReviewLoop._reached_consensus` (mirrored severity set).
2. Approval detection must be per-`commit_id`, not PR-wide — any new
   reviews-API consumer takes `head_sha` as required and filters rows
   first.
3. Prod runs pre-merge code — `review_engine.py` / `review_loop.py` PRs
   should expect the prod-side codex review to saturate before the new
   cap ships. Not a regression; call it out in the PR description.
4. CI flake — `tests/board/test_routes.py::test_backlog_returns_tree` is
   non-deterministic on faster hardware; not your PR's fault if it trips
   while you didn't touch Board.
