# Wave Work Log: t408-structured-logs

**Date:** 2026-05-04
**PR:** [#317](https://github.com/sachinkundu/cloglog/pull/317) — merged
**Task:** T-408 — Structured-events logging for review/webhook/agent contexts

---

## Commits

```
c7d0b69 chore(demo): refresh exemption hash after rebase onto main
3b11620 chore(demo): refresh exemption hash after session-5 fixes
20abf6f fix(logging): T-408 address codex session-5 findings
0bbd96d chore(demo): refresh exemption hash after session-4 fixes
061c23f fix(logging): T-408 address codex session-4 findings
069df00 chore(demo): refresh exemption hash after session-3 fixes
273cd1e fix(logging): T-408 address codex session-3 findings
fbcadfd chore(demo): refresh exemption hash after session-2 fixes
342cc75 fix(logging): T-408 address codex session-2 findings
a5637ee chore(demo): refresh exemption hash after fix commit
eafb7a2 fix(logging): T-408 address codex review findings
8090401 feat(logging): T-408 structured-event logging for review/webhook/agent
```

## Files changed

- `src/shared/log_event.py` — new helper: `log_event(logger, name, **fields)` formats `name key=value ...` lines
- `src/gateway/app.py` — lifespan installs named-logger promotion at INFO; root stays WARNING
- `src/gateway/review_engine.py` — migrated to `log_event`; events: `review.dispatch`, `review.codex`, `review.persist`, `review.finalize`
- `src/gateway/review_loop.py` — migrated to `log_event`; NUL sanitization + DBAPIError guard preserved from T-407 merge
- `src/gateway/webhook_dispatcher.py` — migrated to `log_event`; events: `webhook.received`, `webhook.dispatched`
- `src/agent/services.py` — migrated to `log_event`; events: `agent.online`, `agent.offline`, `agent.task_started`
- `tests/gateway/test_structured_logs.py` — pin tests for event names, correlation key invariant, cardinality rules

---

## What shipped

Structured `name key=value` log events across review/webhook/agent contexts. Grep-by-correlation-key is now possible:
```
grep "pr=sachinkundu/cloglog#317" /tmp/cloglog-prod.log
```
returns the full ordered story for a PR. Five codex review sessions iterated on the implementation before human merge approval.

---

## Merge conflict resolution

T-407 (NUL sanitization + DBAPIError guard on `record_findings_and_learnings`) landed on main while this branch was in codex review. Rebased onto main; one conflict in `src/gateway/review_loop.py`:

- T-407 added NUL sanitization (`strip_nul`) + "don't kill consumer" `DBAPIError` guard on `record_findings_and_learnings` after the outer `except`/`raise`
- T-408 commit `25121e7` moved those calls inside the try block (structural refactor)

Resolution: applied NUL sanitization and nested `DBAPIError` guard to the inside-try version, removing the duplicate after-raise block. T-407's "don't kill consumer" semantics preserved via `try/except DBAPIError/else` pattern.

---

## Learnings & Issues

### Codex exhausted 5 sessions without bot approval

The PR went through 5 codex review cycles without reaching `:pass:`. Final state: human review + merge required. The 5-session cap is enforced by `codex_max_turns` in config. For a purely additive logging task this suggests codex review quality could be improved by better diff context (PR body's "What changed" section should be very explicit about test coverage).

### Rebase on a long-lived branch surfaces conflicts commit-by-commit

A 12-commit branch rebased against 3 merged PRs produced conflicts at the first commit. Git replay each commit independently, so even a "simple" import-addition conflict must be resolved per-commit. `--continue` through 11/11 commits cleanly once first conflict was resolved.

### `review_loop.py` T-407/T-408 interaction

The T-408 refactor (move mark_posted + record_findings_and_learnings inside try) was written against pre-T-407 code. T-407 added important reliability behavior (NUL sanitization, DBAPIError guard with "don't kill consumer" semantics). The correct merge must:
1. Keep the structural position from T-408 (calls inside try block)
2. Preserve the T-407 NUL sanitization via `strip_nul`
3. Preserve T-407's nested `try/except DBAPIError/else` so `record_findings_and_learnings` failures don't propagate to the outer `raise`

This pattern (`try/except E/else`) is the right idiom when you want: "if this call fails with E, handle it softly; only log success in the `else` branch."

---

## State After This Wave

- Structured logging live in review/webhook/agent contexts
- All 1401 tests passing
- PR #317 squash-merged to main
- `wt-t408-structured-logs` worktree to be removed in this close-wave

---

## Shutdown summary

| Worktree | Shutdown path | Tasks |
|----------|--------------|-------|
| wt-t408-structured-logs | direct (main agent session, no separate launcher) | T-408 |
