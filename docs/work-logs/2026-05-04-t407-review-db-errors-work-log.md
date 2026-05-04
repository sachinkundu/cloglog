# Wave: t407-review-db-errors

Single-task wave folding T-407 (Review pipeline: handle DB persistence errors without killing the review).

## Worktree

| Worktree | Branch | PR | Shutdown path |
|----------|--------|----|---------------|
| wt-t407-review-db-errors | wt-t407-review-db-errors | [#316](https://github.com/sachinkundu/cloglog/pull/316) | cooperative + tab-close (T-390 recurrence: exit-on-unregister.sh did not fire) |

## Per-task work log

### T-407 — Review pipeline NUL byte hardening (`from work-log-T-407.md`)

#### What was done

Hardened the review pipeline and all board write paths against NUL bytes (U+0000) that cause asyncpg `UntranslatableCharacterError` when written to PostgreSQL TEXT/JSONB columns.

**`src/shared/text.py`** (new) — `strip_nul(obj)` recursive sanitizer for str/dict/list values; `NulSanitizedModel` Pydantic mixin with `model_validator(mode='before')` that strips NUL from all string fields before validation.

**`src/review/models.py`** — added `outcome: Mapped[str | None]` column to `PrReviewTurn` (VARCHAR 32, nullable).

**`src/review/interfaces.py`** — added `outcome` field to `ReviewTurnSnapshot`; added `set_outcome(...)` to `IReviewTurnRegistry` Protocol.

**`src/review/repository.py`** — `record_findings_and_learnings`: wraps execute in try/except DBAPIError; calls `session.rollback()` then re-raises. New `set_outcome(...)` method updates the `outcome` column on the affected turn.

**`src/gateway/review_loop.py`** — sanitizes findings and learnings through `strip_nul()` before persisting; wraps `record_findings_and_learnings` in try/except DBAPIError; logs structured WARNING; stamps `outcome='db_error'` via `set_outcome`; does NOT propagate the exception (consumer survives).

**Schemas** — applied `NulSanitizedModel` to all write schemas in `src/board/schemas.py`, `src/agent/schemas.py`, `src/document/schemas.py`: ProjectCreate/Update, EpicCreate/Update, FeatureCreate/Update, TaskCreate/Update, CloseOffTaskCreate, ImportTask/Feature/Epic, AddTaskNoteRequest, ReportArtifactRequest, CompleteTaskRequest, UpdateTaskStatusRequest, DocumentCreate.

**Migration** — `src/alembic/versions/479ae109c254_add_outcome_to_pr_review_turns.py` adds `outcome VARCHAR(32) NULL` to `pr_review_turns`.

**Tests** — 8 new tests in `tests/gateway/test_review_loop.py` (strip_nul unit, NUL sanitized before persist, DBAPIError → WARNING log, db_error outcome stamp, consumer survives); 17 tests in new `tests/board/test_task_create_sanitization.py` covering all write schemas.

#### Codex review history

Two rounds. Session 1 flagged 6 schemas missing `NulSanitizedModel` (`ImportTask`, `ImportFeature`, `ImportEpic`, `CloseOffTaskCreate`, `CompleteTaskRequest`, `UpdateTaskStatusRequest`) — all fixed in follow-up commit. Session 2 passed.

#### Residual TODOs / context the next task should know

- **T-409 dependency:** the new `outcome` column and `set_outcome` are live as of this merge. T-409's `failed` codex-status badge can read `outcome='db_error'` directly.
- **`strip_nul` is the single chokepoint** — any future schema accepting free-form text should inherit `NulSanitizedModel`.
- **`record_findings_and_learnings` re-raises DBAPIError after rollback** — intentional, so `review_loop.py` can call `set_outcome` on the same (now clean) session. Don't change the pattern without updating the loop.
- No retry for the failed insert (explicitly out of scope).

## Learnings & Issues

### Recurrence: exit-on-unregister.sh did not fire (T-390)

Same regression as wt-t398: agent emitted `agent_unregistered` cleanly, but the launcher (claude PID + inbox-monitor tail) was still alive when close-wave reached Step 6. Close-wave fell through to `close-zellij-tab.sh` to terminate. T-390 already tracks investigation; second recurrence today.

### Quality gate

`make quality` on `main` after the merge passed. No integration issues.

### Routing

- T-390 recurrence is task-tracked, not docs-tracked.
- No new silent-failure invariants — the NUL-strip behaviour is itself test-pinned via `tests/board/test_task_create_sanitization.py` and `tests/gateway/test_review_loop.py`.
- `strip_nul` chokepoint pattern is documented in the work log; if a future review finds a schema missed `NulSanitizedModel`, the fix is mechanical (add the mixin) and does not warrant a new SKILL/invariant entry.

## State After This Wave

- All board/MCP write paths now strip NUL bytes at the schema boundary; the review loop survives DB persistence errors without killing the consumer.
- `pr_review_turns` carries an `outcome` column ready for T-409's badge state machine.
- Three parallel agents still in flight: T-370 (PR #315 in review), T-408 (PR #317 in_progress), T-409 (PR #318 in review).
