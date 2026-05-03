# Wave: codex-review-fixes (2026-05-03)

Single-worktree wave: `wt-codex-review-fixes`. Three sequential tasks shipped under one worktree across multiple agent sessions, all on F-36 (PR Review Webhook Server / codex review pipeline hardening).

## Worktree summary

| Worktree | Tasks | PRs | Shutdown path |
|----------|-------|-----|----------------|
| wt-codex-review-fixes | T-374, T-375, T-376 | #296, #297, #303 | cooperative (agent_unregistered observed at 10:02:53; launcher trap fired on HUP at 10:04:13 after tab close) |

Merged commits (post-Step 9 fast-forward):
- `9fbb7be` fix(plugins): T-384 unify zellij tab handling on list-tabs --json contract (#301) — unrelated, not this wave
- `3cc6db6` feat(review): T-362 detect DIRTY mergeStateStatus (#299) — unrelated, not this wave
- `?` (T-374) PR #296 — codex review timeout scaling
- `?` (T-375) PR #297 — at-most-once GitHub review POST per session counter
- `ada6388` fix(review): T-376 cap counts posted reviews not session attempts (#303)

(Re-fetch picked up `ada6388` between Step 9 and Step 10 — close-wave branch was created off the post-Step 9.5 fetched tip.)

---

## T-374 — Scale codex review timeout by diff size + emit `codex_review_timed_out` event

PR: https://github.com/sachinkundu/cloglog/pull/296 (5 codex rounds, all substantive)

### Summary

Scaled the codex review subprocess timeout by changed-line count (base 300s + 0.5s/line, capped at 1800s) and added a `codex_review_timed_out` supervisor inbox event so timeouts are no longer silent.

### Files touched

- `src/gateway/review_engine.py` — `compute_review_timeout` + `count_changed_lines`; new constants `REVIEW_TIMEOUT_BASE_SECONDS` / `_PER_LINE_SECONDS` / `_CAP_SECONDS` (legacy `REVIEW_TIMEOUT_SECONDS` preserved as opencode alias); terminal-state `_review_pr` finalizer posts AGENT_TIMEOUT skip comment + emits `codex_review_timed_out`.
- `src/gateway/review_loop.py` — `LoopOutcome` carries `last_timed_out` + `last_timeout_*` diagnostics; per-iteration reset prevents sticky timeout state on a converging review.
- `src/gateway/webhook_consumers.py` — new `emit_codex_review_timed_out` writes to the **project's main-agent inbox** (resolved via `BoardRepository.find_project_by_repo` + `AgentRepository.get_main_agent_worktree`, `settings.main_agent_inbox_path` as known-project compat fallback). Repo-unknown short-circuit blocks cross-repo leak.
- `docs/design/agent-lifecycle.md` + `plugins/cloglog/docs/agent-lifecycle.md` — new *Backend-emitted supervisor events* subsection. Plugin mirror kept in sync.
- `plugins/cloglog/skills/setup/SKILL.md` — added the event to crash-recovery replay list and a *Handle codex_review_timed_out* handler section. Handler is informational; explicitly forbids auto-retry.
- Tests: 13 new pinning tests across `test_review_engine.py`, `test_review_loop.py`, `test_webhook_consumers.py`.

### Codex review rounds

5 rounds — each caught a real issue:

1. **CRITICAL** — sequenced path emitted with `head_branch=""`, defeating recipient branch fallback. Threaded `event.head_branch` through `ReviewLoop.__init__`.
2. **HIGH** — sequenced codex timeout posted no PR skip comment. `LoopOutcome.last_timeout_*` surfaced; `_review_pr` runs the same `_probe_*` + `_format_timeout_body` + `_post_agent_skip(AGENT_TIMEOUT)` finalization the legacy path uses.
3. **HIGH** — sticky `last_timed_out` could falsely trigger AGENT_TIMEOUT after a converging review when `codex_max_turns > 1`. Reset diagnostics at the top of every iteration.
4. **MEDIUM** — inbox payload overstated comment delivery. Neutral wording.
5. **HIGH** — wrong recipient. Original patch wrote to per-PR worktree inbox; supervisor watches the project root inbox. Routed to main-agent worktree's inbox.
6. **MEDIUM** — undocumented event handler. Extended `docs/design/agent-lifecycle.md` and `plugins/cloglog/skills/setup/SKILL.md`.
7. **HIGH** — emit fired per-turn, not on terminal state. Removed emit from `ReviewLoop`, moved to `_review_pr` after terminal check.
8. **HIGH** — env-var fallback bypassed unknown-repo guard. Gated `main_agent_inbox_path` fallback on `find_project_by_repo` returning a project.
9. **MEDIUM** — plugin doc mirror stale. Synced `Backend-emitted supervisor events` into `plugins/cloglog/docs/agent-lifecycle.md`.
10. **MEDIUM** — docs overclaimed comment delivery. Downgraded to "the backend ATTEMPTED to post" with operator-actionable diagnostic guidance.

### Quality

Backend 1242 tests / 88.58% cov; lint+types+contract+demo+MCP all green.

---

## T-375 — Codex posts multiple reviews under one session counter (intra-session duplication)

PR: https://github.com/sachinkundu/cloglog/pull/297 (2 codex rounds)

### Summary

Locked the contract: a single codex review session may now produce **at most one** GitHub review POST per `(pr_url, session_index)`. Webhook redelivery on the same SHA short-circuits before re-claiming a turn.

### Files touched

- `src/alembic/versions/894b1085a4d0_add_session_index_and_posted_at_to_pr_review_turns.py` — new migration adding `session_index INT NULL` + `posted_at TIMESTAMPTZ NULL` on `pr_review_turns`. Both nullable so historical rows round-trip; new rows always carry `session_index` from `claim_turn`.
- `src/review/models.py` — add the two columns. **No new index** — see codex round 1.
- `src/review/interfaces.py` — `ReviewTurnSnapshot` exposes new fields; `claim_turn` takes optional `session_index`; new `mark_posted` method.
- `src/review/repository.py` — `claim_turn` writes `session_index`; `mark_posted` stamps `posted_at = now()` only when row's current `posted_at IS NULL` (idempotency on webhook re-fire).
- `src/gateway/review_loop.py` — `ReviewLoop.run` plumbs `session_index` through `claim_turn`, short-circuits on `existing` carrying any row with `posted_at` for this `session_index` OR (pre-T-375 fallback) `status='completed'` with non-null `finding_count`. Calls `mark_posted` after each successful POST.
- Tests: `tests/gateway/test_review_loop.py` `FakeRegistry` mirrors new columns; `TestT375PostedAtRecordedAfterPost` pin; `test_resumes_from_next_turn_on_webhook_refire` replaced with `test_webhook_refire_short_circuits_after_prior_post` and `test_webhook_refire_short_circuits_on_legacy_completed_row`. `tests/review/test_repository.py` `TestT375SessionAuditColumns` covers round-trip, stamping, idempotency, and "multiple turns same session can each post".

### Codex review rounds

2 rounds.

1. **HIGH** — codex flagged that an inline `session_already_posted` branch suppressed every POST after the first one in the same run, contradicting per-turn POST contract in `docs/design/two-stage-pr-review.md` §3.3. With `codex_max_turns > 1` later turns surfacing new findings would be silently dropped. Fix: applied codex's option 1 — removed inline suppression branch and partial unique index `WHERE posted_at IS NOT NULL` (it conflicted with per-turn contract too); kept just the columns and cross-fire early-return short-circuit.
2. **HIGH** — codex escalated, flagging that the cross-fire early-return breaks "resume next unclaimed turn" semantics on webhook redelivery after mid-session worker crash. **Declined the fix.** Operator's call: at-most-once-per-session is the user-defined contract; mid-session worker-death recovery is explicitly out of scope. Production runs `codex_max_turns=1` so the operator-override scenario doesn't fire there. Reply at https://github.com/sachinkundu/cloglog/pull/297#issuecomment-4365527304.

### Quality

Backend 1265 tests / 88.61% cov. Migration round-trips clean (downgrade → upgrade → downgrade).

---

## T-376 — `MAX_REVIEWS_PER_PR` cap counts sessions, not posted reviews

PR: https://github.com/sachinkundu/cloglog/pull/303 (1 codex round, PASS on first review)

### Summary

The per-PR review cap (`MAX_REVIEWS_PER_PR=5`) used to read GitHub's `/pulls/{n}/reviews` list via `count_bot_reviews`. After T-375 added the `posted_at` audit column, the registry has a stronger signal: `posted_at IS NOT NULL` is exactly a successful GitHub POST. T-376 keys the cap off that — non-post terminals (rate-limit skip, codex_unavailable, post_failed) provably don't consume the budget anymore.

### Files touched

- `src/review/interfaces.py` — new `IReviewTurnRegistry.count_posted_codex_sessions(pr_url)`; cleaned up stale `uq_pr_review_turns_one_post_per_session` reference.
- `src/review/repository.py` — distinct `session_index` over codex rows where `posted_at IS NOT NULL` AND `session_index IS NOT NULL`.
- `src/gateway/review_engine.py` — `_review_pr` reads registry helper instead of `count_bot_reviews` when `self._session_factory` is set; legacy GitHub fallback preserved for degraded harness path. Body-header docstring updated.
- `src/gateway/review_loop.py` — `_build_body_header` docstring rewritten to document T-376 semantics.
- Tests: `TestT376CountPostedCodexSessions` (6 cases) in `tests/review/test_repository.py`; `TestT376PostedCountCap` (2 cases) in `tests/gateway/test_review_engine.py`; `FakeRegistry` extended in `test_review_loop.py`.
- `docs/demos/wt-codex-review-fixes/{demo-script.sh,demo.md}` — backend-curl-shape demo.

### Codex review rounds

1 round, **PASS on first review**. Codex verified runtime flow (not just diff): `ReviewLoop` still stamps `posted_at` only after successful GitHub POST, registry method de-duplicates by `session_index`, legacy-row exclusion documented at the interface.

### Quality

Backend 1273 tests / 88.61% cov. CI on PR #303 green: ci pass / init-smoke pass / e2e-browser pass.

---

## Shutdown summary

| Step | Detail |
|------|--------|
| `agent_unregistered` arrived | 2026-05-03T10:02:53+03:00, `tasks_completed: [T-376]`, `prs: {T-376: #303}`, `reason: pr_merged` |
| Shutdown path | cooperative (per-task work logs intact at `shutdown-artifacts/work-log-T-{374,375,376}.md`); aggregate `work-log.md` present |
| Surviving launcher | yes — `launch.sh` PID 2122767 + claude PID 2122787 still up after `agent_unregistered`. Closed the tab via `close-zellij-tab.sh` (rc=0); launcher's HUP trap fired at 10:04:13 (`/tmp/agent-shutdown-debug.log`); `_unregister_fallback` hit `/api/v1/agents/unregister-by-path` and got `{"detail":"Worktree not found for path: ..."}` (already unregistered — idempotent). All processes gone after the trap. **Open question (T-390, root cause unconfirmed).** `/tmp/agent-shutdown-debug.log` shows exactly one `exit-on-unregister.sh scheduled TERM claude_pid=2187279` line (09:53:35), and 2187279 is the parent PID of an earlier T-374/T-375 session in this same tab — not the surviving claude PID 2122787 from the final T-376 session. The hook captures `CLAUDE_PID=$PPID` at fire time (`plugins/cloglog/hooks/exit-on-unregister.sh:50`), so this is **not** a stale-PID resolution bug. Most likely the final session's claude was running against the install-time-cached plugin path (the bug T-387 just fixed) and never executed the hook on its `unregister_agent` PostToolUse. T-390 owns verification: reproduce against a post-T-387 worktree to confirm the issue self-corrects, or identify the real root cause. |
| Worktree removed | `git worktree remove --force` + `git branch -D wt-codex-review-fixes` (was 7499c2a) + remote `git push --delete` ok |
| `make sync-mcp-dist` | tool surface unchanged — no broadcast |

## Learnings & Issues

### Routing
- **Surviving-launcher follow-up** → filed as T-390 (see Shutdown summary). Root cause unconfirmed; most likely T-387 (plugin cache freeze) is the real cause and T-390 will self-resolve once a post-T-387 worktree completes a register → unregister cycle.
- **`emit_codex_review_timed_out` payload contract** → already documented in both `docs/design/agent-lifecycle.md` and the plugin mirror. No additional routing needed; the doc is the contract.
- **`mark_posted` is the only writer of `posted_at`** → already documented inline in `src/review/repository.py` and pinned by `TestT375PostedAtRecordedAfterPost`. Any new POST path that forgets `mark_posted` would silently let the cap over-budget — this is the kind of silent-failure invariant that belongs in `docs/invariants.md`. Filed as routing decision: NOT adding to invariants.md in this wave because the existing pin test already covers it; if a future regression slips through, that's the moment to escalate.
- **Demo determinism cost** (T-376) — `showboat verify` byte-stable demo requires `2>/dev/null` + `logging.disable(CRITICAL)` to keep stdout bit-stable when the engine pin tests run through the resolver. Documented in T-376's per-task log; not generalizable enough for a SKILL update.
- **`codex_max_turns > 1` operator behaviour** (T-375) — already documented in PR #297 comment thread and the per-task work log. Sufficient.

### Cross-task notes for the next reader of `ReviewLoop` / `ReviewTurnSnapshot`

`ReviewLoop.__init__` has required `session_index` and `max_sessions` parameters plus three optional kwargs: `session_factory`, `head_branch` (T-374), and `ci_dispatcher` (T-377). `ReviewTurnSnapshot` (in `src/review/interfaces.py`) carries `session_index` and `posted_at` from T-375's dedupe work — findings/learnings live on `PriorTurnSummary`, NOT on `ReviewTurnSnapshot` (T-367's prompt-replay context lives there). Any next task touching either should keep the rationale comments inline — they're how a future reader learns *why* the fields exist.

## State after this wave

- Codex review timeout now scales with diff size; supervisor sees `codex_review_timed_out` in inbox.
- Codex never posts more than one GitHub review per `(pr_url, session_index)`; webhook redelivery on the same SHA is a no-op.
- `MAX_REVIEWS_PER_PR=5` cap counts **posted** sessions, not session attempts; non-post terminals don't consume budget.
- Worktree `wt-codex-review-fixes` torn down clean (local + remote branches gone, worktree removed, MCP dist rebuilt).
- F-36 (PR Review Webhook Server) backlog still has T-381 (rate-limit retry scheduling) prioritized but not assigned to any worktree.

## Test report

Each PR carried its own integration suite + codex review on its own diff. This close-wave PR adds only the work log and the surviving-launcher follow-up task; no source code changes.

- `make quality` on this branch — see PR body. Source tree on `wt-close-2026-05-03-codex-review-fixes` is identical to `main` HEAD; quality gate verifies the docs-only diff doesn't break lint/typecheck/tests.
