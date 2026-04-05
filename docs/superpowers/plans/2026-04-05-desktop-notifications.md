# F-17: Desktop Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Notify the user (desktop + in-app) when a task moves to review, so the review process doesn't stall.

**Architecture:** Backend event bus listener creates notification records and fires `notify-send`. New API endpoints serve notifications to the frontend. A bell widget in the header shows unread count and dropdown list. Auto-dismiss on task view.

**Tech Stack:** Python/FastAPI (backend listener, model, endpoints), Alembic (migration), TypeScript/React (notification bell component), `notify-send` (desktop notifications)

---

### Task 1: Add Notification model, migration, and repository methods

**Files:**
- Modify: `src/board/models.py`
- Create: `src/alembic/versions/b1c2d3e4f5a6_add_notifications.py`
- Modify: `src/board/repository.py`
- Modify: `src/shared/events.py`

- [ ] **Step 1: Add NOTIFICATION_CREATED event type**

In `src/shared/events.py`, add after `BULK_IMPORT`:

```python
    NOTIFICATION_CREATED = "notification_created"
```

- [ ] **Step 2: Add Notification model**

In `src/board/models.py`, add after the `TaskNote` class:

```python
class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[_uuid.UUID] = mapped_column(
        primary_key=True, default=_uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[_uuid.UUID] = mapped_column(ForeignKey("projects.id"))
    task_id: Mapped[_uuid.UUID] = mapped_column(ForeignKey("tasks.id"))
    task_title: Mapped[str] = mapped_column(String(500))
    task_number: Mapped[int] = mapped_column(default=0)
    read: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
```

- [ ] **Step 3: Create Alembic migration**

Create `src/alembic/versions/b1c2d3e4f5a6_add_notifications.py` with the notifications table schema. Down revision is `a7b8c9d0e1f2`. Include index on `(project_id, read)`.

- [ ] **Step 4: Run migration**

Run: `uv run python -m alembic upgrade head`

- [ ] **Step 5: Add repository methods**

In `src/board/repository.py`, add import for `Notification` and these methods: `create_notification`, `get_unread_notifications`, `mark_notification_read`, `mark_all_notifications_read`, `get_unread_notification_for_task`. See spec for exact signatures.

- [ ] **Step 6: Run tests to verify nothing broke**

Run: `uv run pytest tests/ -v`

- [ ] **Step 7: Commit**

```bash
git add src/shared/events.py src/board/models.py src/board/repository.py src/alembic/versions/b1c2d3e4f5a6_add_notifications.py
git commit -m "feat(notifications): add Notification model, migration, and repository methods"
```

---

### Task 2: Add notification API endpoints

**Files:**
- Modify: `src/board/routes.py`
- Test: `tests/board/test_routes.py`

- [ ] **Step 1: Write failing tests for notification endpoints**

Add tests to `tests/board/test_routes.py`:
- `test_get_notifications_returns_unread` — creates project, GETs notifications, expects empty list
- `test_mark_notification_read` — PATCHes non-existent notification, expects 404
- `test_mark_all_notifications_read` — POSTs read-all, expects `{"marked_read": 0}`

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/board/test_routes.py -k "notification" -v`

- [ ] **Step 3: Add notification endpoints to board routes**

In `src/board/routes.py`, add three endpoints:
- `GET /projects/{project_id}/notifications` — returns unread notifications as list of dicts
- `PATCH /notifications/{notification_id}/read` — marks one as read, 404 if not found
- `POST /projects/{project_id}/notifications/read-all` — marks all read, returns `{"marked_read": count}`
- `POST /projects/{project_id}/notifications/dismiss-task/{task_id}` ��� marks notification for specific task as read, returns `{"dismissed": bool}`

- [ ] **Step 4: Run notification tests**

Run: `uv run pytest tests/board/test_routes.py -k "notification" -v`

- [ ] **Step 5: Commit**

```bash
git add src/board/routes.py tests/board/test_routes.py
git commit -m "feat(notifications): add GET/PATCH/POST notification endpoints"
```

---

### Task 3: Add global event bus subscriber and notification listener

**Files:**
- Modify: `src/shared/events.py`
- Create: `src/gateway/notification_listener.py`
- Modify: `src/gateway/app.py`
- Create: `tests/gateway/test_notification_listener.py`

- [ ] **Step 1: Add global subscriber support to EventBus**

Add `subscribe_all()` and `unsubscribe_all()` methods to `EventBus` in `src/shared/events.py`. These maintain a `_global_subscribers` list that receives ALL events regardless of project_id. The `publish` method must fan out to both per-project and global subscribers.

- [ ] **Step 2: Write the notification listener**

Create `src/gateway/notification_listener.py` with an `async def run_notification_listener()` function that:
1. Calls `event_bus.subscribe_all()` to get a queue
2. Loops forever reading events from the queue
3. Filters for `TASK_STATUS_CHANGED` where `new_status == "review"`
4. For matching events: queries task from DB, creates notification record, emits `NOTIFICATION_CREATED` event
5. If `os.environ.get("DISPLAY")` is set, fires `notify-send` via `asyncio.create_subprocess_exec` (best-effort, catches FileNotFoundError)

The listener creates its own DB session via `async_session_factory` (not request-scoped).

- [ ] **Step 3: Write tests for the notification listener**

Create `tests/gateway/test_notification_listener.py` with three tests:
- `test_listener_creates_notification_on_review` — mocks session/repo, verifies `create_notification` called and `NOTIFICATION_CREATED` event published
- `test_listener_fires_notify_send_when_display_set` — patches `os.environ` with DISPLAY=:1, verifies `create_subprocess_exec` called with correct args
- `test_listener_skips_notify_send_when_no_display` — patches `os.environ` as empty dict, verifies `create_subprocess_exec` NOT called

- [ ] **Step 4: Run listener tests**

Run: `uv run pytest tests/gateway/test_notification_listener.py -v`

- [ ] **Step 5: Register listener in FastAPI lifespan**

In `src/gateway/app.py`, add an `asynccontextmanager` lifespan that creates an `asyncio.create_task` for `run_notification_listener()`. Cancel on shutdown. Pass `lifespan=lifespan` to `FastAPI()`.

- [ ] **Step 6: Run full backend tests**

Run: `uv run pytest tests/ -v`

- [ ] **Step 7: Commit**

```bash
git add src/shared/events.py src/gateway/notification_listener.py src/gateway/app.py tests/gateway/test_notification_listener.py
git commit -m "feat(notifications): event bus global subscriber + notification listener with notify-send"
```

---

### Task 4: Frontend notification API client and types

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/hooks/useSSE.ts`

- [ ] **Step 1: Add Notification type and update SSEEvent**

In `frontend/src/api/types.ts`:
- Add `Notification` interface: `id`, `project_id`, `task_id`, `task_title`, `task_number`, `read`, `created_at`
- Add `'notification_created'` to `SSEEvent` type union

- [ ] **Step 2: Add notification API methods**

In `frontend/src/api/client.ts`:
- `getNotifications(projectId)` → GET `/projects/{id}/notifications`
- `markNotificationRead(notificationId)` → PATCH `/notifications/{id}/read`
- `markAllNotificationsRead(projectId)` → POST `/projects/{id}/notifications/read-all`
- `dismissTaskNotification(projectId, taskId)` → POST `/projects/{id}/notifications/dismiss-task/{taskId}`

- [ ] **Step 3: Add notification_created to useSSE listener array**

- [ ] **Step 4: Run frontend tests**

Run: `cd frontend && npx vitest run`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/hooks/useSSE.ts
git commit -m "feat(frontend): add notification API client, types, and SSE event"
```

---

### Task 5: Frontend NotificationBell component

**Files:**
- Create: `frontend/src/components/NotificationBell.tsx`
- Create: `frontend/src/components/NotificationBell.css`
- Create: `frontend/src/components/NotificationBell.test.tsx`
- Modify: `frontend/src/components/Layout.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Write failing tests**

Create `frontend/src/components/NotificationBell.test.tsx` with 4 tests:
- `shows badge with unread count` — mock 2 notifications, verify badge shows "2"
- `hides badge when no unread notifications` — mock empty, verify no badge
- `clicking notification calls onNavigate` — click item, verify onNavigate('task', taskId) and markNotificationRead called
- `clear all marks all read` — click "Clear all", verify markAllNotificationsRead called

Props: `projectId: string | null`, `onNavigate: (type, id) => void`

- [ ] **Step 2: Create NotificationBell component**

Create `frontend/src/components/NotificationBell.tsx`:
- Fetches notifications on mount via `api.getNotifications`
- Subscribes to `notification_created` SSE events to refetch
- Bell icon (Unicode bell char) with red badge showing count
- Dropdown on click: list of items, each with `T-{number}: {title}` and relative timestamp
- Click item: mark read, remove from local state, close dropdown, call onNavigate
- Clear all button: mark all read, clear local state, close dropdown
- Close on outside click
- Expose a `__notificationBellRefresh` on window for auto-dismiss integration

- [ ] **Step 3: Create NotificationBell.css**

Styles for: `.notif-bell-wrapper`, `.notif-bell`, `.notif-badge` (red circle), `.notif-dropdown`, `.notif-item`, `.notif-title`, `.notif-time`, `.notif-clear`, `.notif-empty`

- [ ] **Step 4: Add to Layout and App**

In `Layout.tsx`: add `onNavigate` optional prop, render `<NotificationBell>` in `.main-header` next to ThemeToggle.
In `App.tsx`: pass `onNavigate={openDetail}` to Layout.

- [ ] **Step 5: Run tests**

Run: `cd frontend && npx vitest run`

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/NotificationBell.tsx frontend/src/components/NotificationBell.css frontend/src/components/NotificationBell.test.tsx frontend/src/components/Layout.tsx frontend/src/App.tsx
git commit -m "feat(frontend): add NotificationBell component with badge, dropdown, and SSE updates"
```

---

### Task 6: Auto-dismiss notifications on task view

**Files:**
- Modify: `frontend/src/components/DetailPanel.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Add projectId prop to DetailPanel**

Add `projectId: string` to `DetailPanelProps`. Pass it through to `TaskDetail`.

- [ ] **Step 2: Add auto-dismiss effect to TaskDetail**

In `TaskDetail`, add a `useEffect` that calls `api.dismissTaskNotification(projectId, data.id)` on mount, then calls the bell's refresh function via `(window as any).__notificationBellRefresh`.

- [ ] **Step 3: Pass projectId from App.tsx**

Update `<DetailPanel>` usage in App.tsx to pass `projectId={selectedProjectId}`.

- [ ] **Step 4: Run all tests**

Run: `uv run pytest tests/ -v && cd frontend && npx vitest run`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/DetailPanel.tsx frontend/src/App.tsx
git commit -m "feat(notifications): auto-dismiss notification when viewing task detail"
```

---

### Task 7: Final integration verification

- [ ] **Step 1: Run full quality gate**

Run: `make lint && make typecheck && uv run pytest && cd frontend && npx vitest run`

- [ ] **Step 2: Manual smoke test**

1. Start dev server, open board
2. Move a task to review via MCP or curl
3. Verify: desktop notification appears (if on X11)
4. Verify: bell shows badge, dropdown works, clicking navigates
5. Verify: opening task from board auto-dismisses notification

- [ ] **Step 3: Push**

```bash
git push origin HEAD
```
