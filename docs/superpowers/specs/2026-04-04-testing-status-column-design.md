# Testing Status Column — Design Spec

## Purpose

Add a `testing` status to the task lifecycle so agents must stop and verify their work before requesting review. This creates a gate where test evidence is documented, preventing "it compiles, ship it" behavior.

## Status Lifecycle

```
backlog → assigned → in_progress → testing → review → done
                                                ↕
                                             blocked
```

No hard transition enforcement — any status can move to any status (current behavior). The discipline is in the workflow convention, not the code.

## Backend Changes

### `src/board/routes.py`

Add `"testing"` to `BOARD_COLUMNS` after `"in_progress"`:

```python
BOARD_COLUMNS = ["backlog", "assigned", "in_progress", "testing", "review", "done", "blocked"]
```

### `src/board/services.py` — Roll-up Logic

Update `recompute_rollup` so `testing` is treated like `in_progress` for feature/epic status computation:

- Feature status is `"done"` only when **all** tasks are done
- Feature status is `"review"` when any task is in review and none are in earlier active states
- Feature status is `"in_progress"` when any task is in `in_progress`, `testing`, or `assigned`
- Otherwise `"planned"`

`testing` does NOT get its own feature-level status — it rolls up as `"in_progress"`.

### No Migration Needed

Task status is `String(20)` — no enum constraint in the database.

## Frontend Changes

### `frontend/src/components/Column.tsx`

Add to `COLUMN_LABELS`:

```typescript
testing: 'Testing',
```

The Board component iterates over API response columns, so it renders the new column automatically.

## MCP Server Changes

### `mcp-server/src/server.ts`

Update `update_task_status` tool description to include `testing` in the valid statuses:

```
'Target status: backlog, assigned, in_progress, testing, review, done, blocked'
```

## Workflow Convention

These are process rules for agents, not enforced in code.

### At the `testing` stage — before moving to `review`

The agent must add a task note containing:

- What tests were added or modified
- Test strategy rationale (why these tests cover the change)
- `make quality` output summary (tests, lint, typecheck)
- Current test pass/fail state and coverage

### At the `review` stage — two modes

**Main agent (direct chat with user):**
- Add a task note with manual verification steps the user can perform
- No PR required — user is present in the conversation

**Worktree agent:**
- PR must be created using bot identity
- PR description includes test report section + manual verification steps
- Agent starts `/loop` to watch for review comments
- Task moves to `done` when PR is approved and mergeable

### Moving to `done`

- **Main agent tasks:** User says it's done in chat
- **Worktree agent tasks:** PR approved → agent moves to done

## Out of Scope

- No hard gates or transition validation in the API
- No database migration
- No new API endpoints
- No changes to `complete_task` or `start_task` agent service methods
- No UI changes beyond the new column rendering

## Files to Modify

| File | Change |
|------|--------|
| `src/board/routes.py` | Add `"testing"` to `BOARD_COLUMNS` |
| `src/board/services.py` | Update `recompute_rollup` to handle `testing` |
| `frontend/src/components/Column.tsx` | Add `testing` to `COLUMN_LABELS` |
| `mcp-server/src/server.ts` | Update status description string |
