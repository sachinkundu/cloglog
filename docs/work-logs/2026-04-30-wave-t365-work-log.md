# Wave t365 — 2026-04-30

## Worktree

- **wt-t365-post-review-commit-id** — T-365 — PR #282 — MERGED 2026-04-30T14:52:49Z

### Commits (origin/main..wt-t365-post-review-commit-id)

```
6aaaac1 chore(demo): refresh exemption hash after degraded-path fix commit
33ce428 fix(review): also plumb commit_id through degraded single-turn path (T-365)
c0b6374 chore(demo): add no_demo exemption for T-365
cdb885f fix(review): include commit_id in GitHub review payload (T-365)
```

### Files changed

- `src/gateway/review_engine.py`
- `src/gateway/review_loop.py`
- `tests/gateway/test_review_engine.py`
- `docs/demos/wt-t365-post-review-commit-id/exemption.md`

## Shutdown summary

| Worktree | PR | Shutdown path | Commits |
|---|---|---|---|
| wt-t365-post-review-commit-id | #282 | cooperative | 4 |

Cooperative shutdown — `agent_unregistered` received at 2026-04-30T17:53:51+03:00 with `reason=pr_merged`. No `force_unregister` fallback needed.

## Per-task work log — T-365 (from work-log-T-365.md)

### Summary

Fixed `post_review` to include `commit_id` in the GitHub create-review API payload, ensuring reviews are always stamped against the SHA codex actually reviewed — not whatever the branch HEAD happened to be at API-processing time.

### Files touched

- `src/gateway/review_engine.py` — `post_review` gains `head_sha: str = ""` kwarg; adds `"commit_id": head_sha` to POST payload when non-empty. Also fixed the degraded single-turn path (`session_factory is None`) to forward `head_sha=head_sha`.
- `src/gateway/review_loop.py` — `ReviewLoop.run` passes `head_sha=self._head_sha` to `post_review`.
- `tests/gateway/test_review_engine.py` — added three pin tests: `test_commit_id_included_when_head_sha_provided`, `test_commit_id_omitted_when_head_sha_empty`, and `test_degraded_path_includes_commit_id` (regression for the degraded `session_factory=None` branch).
- `docs/demos/wt-t365-post-review-commit-id/exemption.md` — no_demo classifier exemption (backend-only behaviour fix; no UI surface).

### Codex review findings and resolutions

- **Session 1/5 — MEDIUM:** The degraded single-turn path at `review_engine.py:1470` was still calling `post_review()` without `head_sha` after the main fix. Resolved in commit 33ce428; `test_degraded_path_includes_commit_id` pins the regression.
- **Session 2/5 — `:pass:`** — no issues found.

### Residual TODOs

- **Pre-POST staleness check (out of scope, follow-up).** The fix attributes the review correctly but does not prevent posting against a SHA that has already been superseded at POST time. Optional follow-up: before POST, `gh pr view --json headRefOid`; if disagrees with `head_sha`, log `review_superseded` and drop. One extra round-trip per session.
- The `commit_id` fix immediately unblocks both `count_bot_reviews` dedup (`review_engine.py:1031-1038`) and the auto-merge gate's `latest_codex_review_is_approval` filter (`review_engine.py:1052-1096`) for the antisocial PR scenario — both already filter on `commit_id == head_sha`.

## Learnings & Issues

### Wave-integration findings

- `make sync-mcp-dist` reported "tool surface unchanged — no broadcast" — this PR did not touch `mcp-server/src/`, as expected.
- Quality gate run on the close-wave branch — see Step 10.5 outcome below.

### Cross-wave learnings to fold into CLAUDE.md

**`commit_id` is the bot-attribution contract.** When a GitHub create-review POST omits `commit_id`, GitHub stamps the review with the branch's *current* head at API-processing time — not the SHA the reviewer actually read. Any race between the reviewer's read and a new push silently mis-attributes the review. T-281's temp-checkout dir naming (`<head_sha[:8]>-<pr_number>`) made the discrepancy visible in finding paths but the `commit_id` plumbing had to be fixed for downstream consumers (`count_bot_reviews`, `_codex_passed_for_head`) to be trustworthy. Generalises: any review POST that names a SHA elsewhere (path, body, log) MUST also pass `commit_id` explicitly to keep the GH-stamped attribution consistent. Pin: `tests/gateway/test_review_engine.py::test_commit_id_included_when_head_sha_provided`.

**The degraded review path is real code and needs the same plumbing.** `review_engine.py` has a single-turn fallback for the `session_factory is None` case (no DB-backed registry available — used in tests and degraded boot). It calls `post_review` directly, not through `ReviewLoop`. Any new `post_review` kwarg must be forwarded from BOTH callsites. Codex caught this as a session-1 finding; pin `test_degraded_path_includes_commit_id` blocks regressions.

## State After This Wave

- T-365 shipped — `post_review` now sends `commit_id == head_sha` on every review POST. Both the `ReviewLoop` happy path and the degraded single-turn path are covered.
- `count_bot_reviews` and `_codex_passed_for_head` now receive accurate session/commit attribution from GitHub — no further work needed there.
- T-367 filed (codex exhaustive first-pass + cross-session memory of prior findings) — sequenced after T-365 since cross-session memory depends on `commit_id` integrity.
