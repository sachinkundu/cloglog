# Wave: t381-rate-limit-retry — 2026-05-04

Single-worktree wave: `wt-t381-rate-limit-retry` → PR #309 (merged 2026-05-04T03:52:53Z).

## Shutdown summary

| Worktree | PR | Shutdown path | Notes |
|----------|-----|---------------|-------|
| wt-t381-rate-limit-retry | #309 | cooperative (agent-driven, exit-on-unregister) | shutdown-artifacts inlined below |

## T-381 — Rate-limit skip must schedule a real retry

*from `work-log-T-381.md`*

### Problem

`ReviewEngineConsumer.handle()` posted "Will retry after ~N minutes" when a PR rate-limited but never scheduled a retry — the comment was a lie and the PR sat silent until the author pushed another commit.

### Solution

Schedule a real `asyncio.Task` retry on every rate-limit hit, with a rolling-window-aware queue model so the per-hour cap stays intact and the user-visible comment stays truthful in every operational mode (scheduled, permanent block, capacity exhausted).

### Files touched

- `src/gateway/review_engine.py`
  - `RateLimiter`: per-reservation queue model. `_reservations: list[float]` of wake times; `reserve()` returns the assigned wake time computed by sorting `active + reservations` and placing the new entry at `scheduled[N - max] + RATE_LIMIT_WINDOW_SECONDS`. `consume_reservation(wake)` and `release_reservation(wake)` operate by wake time. New `can_reserve()` (caps `len(reservations) < max`) and `is_permanently_blocked()` (`max_per_hour == 0` sentinel — never numeric `wait_seconds == 0` comparison).
  - `ReviewEngineConsumer.handle()`: synchronous-block-then-await shape. Schedule retry BEFORE awaiting `_notify_skip` so concurrent same-PR webhooks register in arrival order. Success path cancels and releases any pending retry for the same PR.
  - `_schedule_rate_limit_retry`: returns `(scheduled, wake)`; wake stashed on the task as `task._t381_wake` so cancellation paths release the correct queue entry. Cancel-then-reserve net-zero swap always succeeds for replacement pushes.
  - `_run_rate_limit_retry`: sleeps until wake, then `consume_reservation(wake)` (atomic decrement + timestamp append) before invoking `_review_pr` under the engine lock.
  - `_rate_limit_skip_comment`: branches on `(permanent, scheduled)` — three operationally distinct comment bodies covering scheduled / disabled / capacity-exhausted.
- `src/gateway/review_skip_comments.py`
  - Dedupe key now includes `body`: same-body within window suppressed (anti-spam preserved); different body for the same `(repo, pr, reason)` re-posts. Keeps PR comment in sync with rescheduled retry ETAs.
- `tests/gateway/test_review_engine.py`
  - `TestRateLimitRetry` × 10 + 1 in `TestPostSkipComment`: schedule-on-skip, retry-actually-runs (fast-forwarded sleep), second-push-replaces-pending, max=0 permanent leaves `_pending_retries` empty, slot reservation against unrelated PRs, zero-wait-at-boundary still schedules, capacity-full refuses second PR, comment truthfulness for permanent + capacity, max=2 distinct queue slots, concurrent-pushes arrival-order wins, body-aware dedupe.
- `docs/demos/wt-t381-rate-limit-retry/{demo-script.sh,demo.md}` — Showboat demo.

### Codex review rounds

5 rounds before exhausting codex's 5-session quota; final merge on a human-reviewed PR.

1. **Round 1** (HIGH/MEDIUM): stale-retry race on success path; `max_per_hour=0` permanent-block broken by unconditional retry.
2. **Round 2** (HIGH×2, MEDIUM×2): registration-order races against `_notify_skip` POST; sentinel ambiguity (`wait_seconds=0` ≠ permanent block); slot reservation for unrelated PRs.
3. **Round 3** (HIGH, MEDIUM): capacity-blind reservations let multiple PRs reserve the same slot; comment body unconditional even when no retry was scheduled.
4. **Round 4** (MEDIUM): same-batch retries with `max_per_hour > 1` all woke at the first reopened slot (shared `seconds_until_next_slot()`).
5. **Round 5** (HIGH): `post_skip_comment` deduped by `(repo, pr, reason)` only — replacement push's updated ETA was suppressed.

### Test evidence

- `make quality` green at every push: 1310 backend tests + 110 silent-failure invariants + lint + types + contract + demo + MCP.
- 10 new pin tests under `TestRateLimitRetry` plus 1 in `TestPostSkipComment`. Showboat demo verifies live behavior end-to-end.

### Residual TODOs

- **Persistence across backend restart.** Retry task lives in-process; gunicorn restart during the wait window loses the retry and the comment becomes a lie *for that restart event*. Persistent job queue (Redis/Postgres) is a separate, larger design — file as follow-up if a real outage shows the in-process scope is insufficient.
- **No bounded retry chains.** `_run_rate_limit_retry` calls `_review_pr` directly, bypassing the rate limiter on the retry attempt itself (the slot was already promised). If `_review_pr` fails internally (codex unavailable, post failed), the failure is logged but no second retry is queued — intentional simplest contract.
- **`_t381_wake` task attribute is private/load-bearing.** Don't refactor to a parallel dict without preserving the synchronous release-on-cancel guarantee — a separate dict would split atomicity.
- **`reserve()` returns absolute monotonic time, not delay.** Callers compute `delay = max(0, wake - time.monotonic()) + RATE_LIMIT_RETRY_BUFFER_SECONDS`. The 1s buffer survives boundary clock-skew that could otherwise wake the retry milliseconds before the slot is actually free.
- **`SkipReason.RATE_LIMIT` body is part of the dedupe key.** If you change the rate-limit comment template, run `tests/gateway/test_review_engine.py::TestPostSkipComment::test_different_body_same_reason_both_post` to confirm the body still varies enough that dedupe doesn't silently re-suppress.

### Learnings

The five codex rounds collectively are a case study in *concurrent-state racing under a public-facing comment*. The pattern that recurred: every "schedule a side effect" point needed to register state synchronously before awaiting any I/O, because a second webhook for the same PR can land in the arrival-order gap. The discipline ("synchronous register, then await POST, then cancel-and-replace on next event") is reusable beyond rate limiting — it applies to any handler that promises a future side effect via a comment. Not promotable to a generalised pin test, so left in this work log rather than `docs/invariants.md`.

## State after this wave

- Rate-limit skip path now schedules a real `asyncio.Task` retry, with rolling-window-aware reservation; comment body always reflects the operational case (scheduled / permanent / capacity).
- 11 new pin tests + 1 demo. Quality gate: 1310 passed at coverage 88.63%.
- Next: monitor for restart-loss outages; if observed, file the persistent-queue follow-up.
