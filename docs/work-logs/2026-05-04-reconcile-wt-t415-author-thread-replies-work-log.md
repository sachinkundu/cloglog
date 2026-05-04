# Wave: reconcile-wt-t415-author-thread-replies

**Date:** 2026-05-04
**Worktree:** wt-t415-author-thread-replies
**PR:** #320 (merged 2026-05-04 14:01:53 UTC)
**Branch:** wt-t415-author-thread-replies (deleted)
**Mode:** reconcile delegation (close-wave invoked from /cloglog reconcile)

## Shutdown summary

| Worktree | Path | Notes |
|---|---|---|
| wt-t415-author-thread-replies | manual TERM after orphan-launcher detected | Backend session already unregistered (not in `list_worktrees`); shutdown-artifacts present and consolidated. But launcher PID 670755 + claude PID 670775 still alive — same orphan-launcher fingerprint as wt-t416 earlier today. Step 6 caught it; manual `kill -TERM 670755` cleared the tree without `kill -9`. Evidence appended to T-390. |

The agent ran cooperative shutdown correctly (PR merged → mark_pr_merged → review → unregister) but the launcher's `wait` did not return — i.e., `exit-on-unregister.sh` did not TERM claude. T-390 already tracks this regression; this wave adds another data point — three of three worktrees today (T-415, T-416, T-419) hit it.

## Commits on `wt-t415-author-thread-replies`

```
2a08b86 chore(t415): refresh exemption hash after mismatch-guard commit
096a714 fix(t415): guard against review-count mismatch when findings not persisted
afc54ae chore(t415): refresh exemption diff_hash after v3 commit
bdd03bd fix(t415): v3 — composite key + index-based reply matching
690d273 chore(demo): T-415 refresh exemption hash after codex-review fixes
7e6a6ab fix(review): T-415 address codex review — scope replies to PR author and specific turn's review
d3d254e chore(demo): T-415 add classifier exemption — internal prompt wiring, no user-observable surface
b3c3da7 feat(review): T-415 wire author thread replies into Prior review history preamble
```

## Files changed

- `src/gateway/review_thread_replies.py` (new) — `enrich_prior_context()` async entry point + `_build_enriched_turns()` pure matcher.
- `src/review/interfaces.py` — added `author_responses: dict[str, str | None]` to `PriorTurnSummary`.
- `src/gateway/review_loop.py` — `_render_prior_history_section` uses real replies; `(not fetched)` literal removed.
- `src/gateway/review_engine.py` — calls `enrich_prior_context` after `prior_findings_and_learnings`.
- `tests/gateway/test_review_loop_t415_author_replies.py` (new) — 18 tests.
- `docs/demos/wt-t415-author-thread-replies/exemption.md` — classifier exemption (internal prompt wiring).

## Inlined per-task work log (`work-log-T-415.md`)

### What was built

Replaced the hard-coded `Author response: (not fetched)` placeholder in `_render_prior_history_section` with real GitHub review-thread author replies. New module `src/gateway/review_thread_replies.py`:

- `enrich_prior_context()` — async entry point; fetches all PR reviews + inline comments from GitHub in parallel via `asyncio.gather`, falls back to original context on any error.
- `_build_enriched_turns()` — pure matching (no I/O). Composite key `(head_sha, turn_number)` to match prior turns to GitHub reviews, body-match (`"**[SEVERITY]** body"`) to map findings to root comments, responses keyed by finding index `str(idx)`.

### Codex iterations (5 sessions to consensus)

- Session 1 `:warning:` → fixed: author-login filter, review_id scoping, composite SHA key.
- Session 2 `:warning:` → fixed: composite `(head_sha, turn_number)` + index-based responses with body matching.
- Session 3 `:warning:` → exemption diff_hash refresh.
- Session 4 `:warning:` → fixed: count-mismatch guard for `db_error` path (degrade gracefully, don't misattribute).
- Session 5 `:pass:` → approved.

### Decisions

- Index-based reply key (`str(idx)`) over `file:line` — same-location findings are real and need to be distinguishable.
- 500-char reply truncation — codex doesn't need full "won't fix" walls of text.
- Body-match fallback for minimal test fixtures; production findings always have severity + body.

### Test evidence

18 new tests under `tests/gateway/test_review_loop_t415_author_replies.py` covering AC4 (a/b/c render shapes), matching logic (author filter, opencode isolation, cross-commit isolation, two-turns-same-SHA, mismatch guard), and error fallback. `make quality` green; CI green.

### Residual TODOs / context

1. **Proper fix for the mismatch guard.** The count-based guard (`_build_enriched_turns` lines ~121-130) is safe-but-lossy. Correct fix: store `github_review_id` (BIGINT) on `pr_review_turns`, return it from `post_review()`, expose via `IReviewTurnRegistry`, drop the count guard. Files an Alembic migration. — file as a follow-up task if you want it done.
2. `pr_author_login` defaults to `""` if `pull_request.user.login` is absent (edge case) → all replies filtered out. Not seen in production but worth noting.
3. Reply truncation at 500 chars is intentional. If a finding really needs more, expand.
4. Body matching needs both `severity` and `body` on findings — production always has them; sole-root fallback covers minimal fixtures.

## Learnings & Issues

- **Orphan-launcher regression (T-390) is now 100% repro on this host.** All three worktrees today (T-415, T-416, T-419) needed manual TERM after `agent_unregistered`. Either `mcp__cloglog__unregister_agent` is not being invoked by the agent, or the PostToolUse hook `exit-on-unregister.sh` is not firing. T-390 has the data; needs prioritisation.
- **Codex EXHAUSTED badge fires too early (T-424).** Filed during this wave after spotting `https://github.com/sachinkundu/antisocial/pull/41` showing EXHAUSTED with 2 PR-wide sessions still available. Root cause: badge uses per-session `codex_max_turns` (default 1) instead of PR-wide `MAX_REVIEWS_PER_PR` (5).
- **Cross-project DB contamination via psql.** `cloglog_dev` is shared with other projects' boards, and a SELECT without `project_id` filter pulls them in. Filed T-417 for hookify guard; the lesson is "use MCP, not psql" — exactly what the existing rule already says.
- **Mismatch-guard fallback is lossy by design.** When `pr_review_turns.findings_json` is missing for a SHA (a `db_error` outcome), the matcher returns `None` for all turns rather than misattribute. This is the right tradeoff today; the structural fix (per residual TODO #1) eliminates it.

## State after this wave

- T-415 implementation merged in main (head `addcc75`).
- Codex prior-history preamble now carries real author replies, not the placeholder.
- The "is this finding addressed?" question codex answers on turn 2+ now has the author's GitHub thread reply as evidence, per the prompt's spec.
- Two close-waves done today (T-416, T-415); one more (T-419) follows immediately as the second reconcile delegation.
- Outstanding sibling: T-419 worktree still on disk; close-wave delegation continues right after this commit.
