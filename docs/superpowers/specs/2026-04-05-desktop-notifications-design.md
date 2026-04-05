# F-17: Desktop Notifications for Review Requests

**Date:** 2026-04-05
**Feature:** F-17 Desktop Notifications for Review Requests (Epic: Operations & Reliability)

## Problem

When an agent moves a task to review, the user has no way to know unless they're actively watching the board. The user is not always watching the terminal or the browser tab. They need to be notified when work is ready for review so the process doesn't stall.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Trigger event | `task_status_changed` where `new_status == "review"` only | YAGNI — review requests are the only notification that matters now |
| Desktop delivery | `notify-send` from backend, best-effort | Backend is always running. Skip silently if `DISPLAY` not set. |
| Persistence | Notification records in DB | Frontend queries on load, so notifications survive tab close/reopen |
| Dismissal | Auto-dismiss on task view + manual clear | Natural flow: viewing the task means you've seen it. Manual clear for bulk. |

## Backend: Notification Storage

### New table: `notifications`

```
id: UUID (PK)
project_id: UUID (FK → projects)
task_id: UUID (FK → tasks)
task_title: str
task_number: int
read: bool (default false)
created_at: datetime(tz)
```

Index on `(project_id, read)` for efficient unread queries.

### Event Bus Listener

A listener registers in the FastAPI app lifespan (`app.py`). It subscribes to the event bus for all projects and filters for `TASK_STATUS_CHANGED` events where `new_status == "review"`.

When triggered:
1. Query the task from the DB using `task_id` from the event data to get `title` and `number` (the event only carries `task_id`, `old_status`, `new_status`)
2. Insert a notification record into the `notifications` table
3. If `os.environ.get("DISPLAY")` is set, run `notify-send "cloglog" "T-{number}: {title} is ready for review"` via `asyncio.create_subprocess_exec`. If `DISPLAY` is not set, skip silently.
4. Emit `NOTIFICATION_CREATED` event for SSE fan-out

The listener needs its own database session (not tied to a request). It creates a session from the `async_session_factory` directly.

### New API Endpoints

All under the board routes (public, no auth — dashboard-facing):

- `GET /projects/{project_id}/notifications` — returns unread notifications, newest first
- `PATCH /notifications/{notification_id}/read` — marks one notification as read
- `POST /projects/{project_id}/notifications/read-all` — marks all notifications for the project as read

Response schema for a notification:
```json
{
  "id": "uuid",
  "project_id": "uuid",
  "task_id": "uuid",
  "task_title": "string",
  "task_number": 0,
  "read": false,
  "created_at": "datetime"
}
```

### SSE Event

When a notification is created, emit a new `NOTIFICATION_CREATED` event so the frontend can update the badge count without polling. Add this to the `EventType` enum.

## Frontend: Notification Widget

### Bell Icon

Located in the main header (`Layout.tsx`), next to the ThemeToggle. Shows a red count badge when unread notifications exist (e.g., "3"). No badge when count is zero.

### Dropdown

Clicking the bell opens a dropdown list:
- Each entry: `T-{number}: {title}` with relative timestamp ("2 min ago")
- Clicking an entry: navigates to the task detail panel, auto-marks notification as read
- "Clear all" button at the bottom: calls `POST /read-all`
- Clicking outside the dropdown closes it

### SSE Integration

The widget listens for `notification_created` SSE events to increment the badge count in real-time. On mount, it fetches `GET /notifications` to get the current unread count.

### Auto-Dismiss on Task View

When the detail panel opens for any task (from board, backlog, or notification click), check if there's an unread notification for that task_id. If so, call `PATCH /notifications/{id}/read` and update the local state.

## Files Changed

| File | Change |
|------|--------|
| `src/shared/events.py` | Add `NOTIFICATION_CREATED` event type |
| `src/board/models.py` | Add `Notification` model |
| `src/board/repository.py` | Add notification CRUD methods |
| `src/board/routes.py` | Add 3 notification endpoints |
| `src/gateway/app.py` | Register notification event listener in lifespan |
| `src/alembic/versions/...` | Migration for `notifications` table |
| `frontend/src/api/client.ts` | Add notification API methods |
| `frontend/src/api/types.ts` | Add `Notification` type, update `SSEEvent` |
| `frontend/src/hooks/useSSE.ts` | Add `notification_created` to listener array |
| `frontend/src/components/NotificationBell.tsx` | New component: bell icon + dropdown |
| `frontend/src/components/NotificationBell.css` | Styles for bell, badge, dropdown |
| `frontend/src/components/Layout.tsx` | Add NotificationBell to header |
| `frontend/src/components/DetailPanel.tsx` | Auto-dismiss notification on task view |

## Testing Strategy

### Backend
- Unit test: listener creates notification when task moves to review
- Unit test: listener ignores other status transitions (in_progress, done, backlog)
- Unit test: `notify-send` called when DISPLAY set, skipped when not
- Integration test: GET returns unread, PATCH marks read, POST read-all clears all

### Frontend
- Component test: bell shows badge with unread count
- Component test: clicking notification triggers navigation
- Component test: "Clear all" calls read-all endpoint
- Integration test: opening task detail auto-dismisses notification
