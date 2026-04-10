# Demo: Drag-and-Drop Bug Fixes (T-138)

Three fixes for Kanban board card drag-and-drop behavior.

## Bug 1: Wrong notification on done→review

**Before:** Dragging a card from done to review fired a "ready for review" notification, even though the user initiated the move.

**After:** User-initiated drags to review auto-dismiss the notification via `dismissTaskNotification` API. Notifications only appear when agents move tasks to review.

**Implementation:** `Board.tsx` `handleDragEnd` calls `api.dismissTaskNotification(projectId, task.id)` after successful update to "review" status.

## Bug 2: Drop shadow artifact

**Before:** Drag preview showed an oversized shadow from the `card-enter` animation and unconstrained card width.

**After:** Drag overlay card is constrained to `max-width: 280px`, uses a controlled `box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2)`, and the `card-enter` animation is disabled on the ghost.

**Implementation:** Added `.drag-overlay-card .task-card` CSS rules in `Board.css`.

## Bug 3: Board flash on drop

**Before:** Dropping a card triggered a full board refetch (`onRefresh()`), causing all cards to re-render with the `card-enter` animation (flash).

**After:** Uses optimistic local state update (`moveTask` in `useBoard`) — the card moves instantly in the UI without network round-trip. The SSE handler skips no-op moves for tasks already in the target column, preventing double-render. Full refetch only happens on API failure (rollback).

**Implementation:**
- `useBoard.ts`: Added `moveTask()` for optimistic column-to-column moves
- `useBoard.ts`: SSE handler checks `col.status === new_status` before moving
- `Board.tsx`: `handleDragEnd` calls `onMoveTask` instead of `onRefresh`

## Test Results

```bash
cd frontend && NO_COLOR=1 npx vitest run 2>&1 | grep "Tests"
```

```output
      Tests  198 passed (198)
```

### New tests added (5)
- `useBoard > moveTask optimistically moves a task to a new column`
- `useBoard > moveTask is a no-op when task is already in the target column`
- `useBoard > SSE task_status_changed is a no-op when task is already in the target column`
- `Board > accepts onMoveTask prop for optimistic drag updates`
- `Board > drag overlay card has compact styling (max-width set)`
