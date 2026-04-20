# Work Log: wt-reviewer-reliability

**Date:** 2026-04-20
**Worktree:** wt-reviewer-reliability
**Tasks:** T-238 + T-239 (shipped as PR #161)
**Feature:** F-36 (PR Review Webhook Server)

## What the PR delivered

- Every silent short-circuit in `src/gateway/review_engine.py` now posts a PR
  comment as the Codex reviewer bot. Six skip sites wired:
  rate limit, `MAX_REVIEWS_PER_PR` cap, no reviewable files, oversize diff,
  unparseable agent output, subprocess timeout.
- New module `src/gateway/review_skip_comments.py`:
  `SkipReason` StrEnum + `post_skip_comment()` + in-memory LRU that
  suppresses identical `(repo, pr, reason)` triples within a rolling hour.
- Timeout path (T-239) rebuilt:
  - captures buffered stderr via `_drain_stderr_after_timeout(proc)` before
    `proc.kill()`,
  - runs parallel probes `_probe_codex_alive()` + `_probe_github_reachable()`,
  - retries the subprocess ONCE if the first attempt timed out,
  - emits a structured `review_timeout` log entry with every field F-49's
    supervisor needs (`event`, `pr_number`, `attempt`, `stderr_excerpt`,
    `codex_alive`, `codex_probe`, `github_reachable`, `github_probe`,
    `elapsed_seconds`).
- `RateLimiter.seconds_until_next_slot()` added so the rate-limit comment
  can tell the author when to retry.

## Test delta

- `tests/gateway/test_review_engine.py` grew from 71 to 97 cases (+26):
  `TestPostSkipComment` (5), `TestSkipCommentsInHandler` (6 including
  happy-path regression guard), `TestTimeoutRetryAndProbes` (4),
  `TestRateLimiterWaitSeconds` (4), `TestProbes` (6),
  `TestNotifySkipErrorPaths` (1).
- Coverage on touched modules: `review_skip_comments.py` 100%,
  `review_engine.py` 86%. Repo total 80.47% (threshold 80%).

## Demo

`docs/demos/wt-reviewer-reliability/demo.md` — drives each of the six skip
paths against a respx-mocked GitHub API; `drive_skip_reasons.py` prints a
deterministic `reason … comments_posted=1 OK` table ending in `ALL OK`.

## Non-scope held

- `REVIEW_TIMEOUT_SECONDS` stayed at 300s — fix is retry + diagnostics,
  not a longer leash.
- No config migration, no new env vars — `make promote` picks it up on merge.
