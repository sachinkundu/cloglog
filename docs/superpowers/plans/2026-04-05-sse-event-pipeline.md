# F-5: SSE Event Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Emit SSE events for all board entity CRUD operations so the dashboard updates in real-time without page refresh.

**Architecture:** Add 8 new event types to the shared EventType enum. Emit events from route handlers (not services) to respect DDD boundaries. The frontend already refetches on unknown events via the `useBoard.ts` fallback handler — we only need to add new event type names to the `useSSE.ts` listener array.

**Tech Stack:** Python/FastAPI (backend event emission), TypeScript/React (frontend SSE listener)

---

### Task 1: Add new event types to shared enum

**Files:**
- Modify: `src/shared/events.py:11-15`

- [ ] **Step 1: Write the failing test**

Add to `tests/board/test_routes.py` at the end of the file:

```python
async def test_create_epic_emits_event(client: AsyncClient):
    """Creating an epic emits an EPIC_CREATED event."""
    project = (await client.post("/api/v1/projects", json={"name": "epic-event-test"})).json()

    with patch("src.board.routes.event_bus.publish", new_callable=AsyncMock) as mock_publish:
        resp = await client.post(
            f"/api/v1/projects/{project['id']}/epics",
            json={"title": "New Epic"},
        )
        assert resp.status_code == 201
        mock_publish.assert_called_once()
        event = mock_publish.call_args[0][0]
        assert event.type == "epic_created"
        assert str(event.project_id) == project["id"]
        assert event.data["title"] == "New Epic"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/board/test_routes.py::test_create_epic_emits_event -v`
Expected: FAIL — `"epic_created"` is not a valid EventType value.

- [ ] **Step 3: Add all 8 new event types**

In `src/shared/events.py`, add to the `EventType` enum:

```python
class EventType(StrEnum):
    TASK_STATUS_CHANGED = "task_status_changed"
    WORKTREE_ONLINE = "worktree_online"
    WORKTREE_OFFLINE = "worktree_offline"
    DOCUMENT_ATTACHED = "document_attached"
    EPIC_CREATED = "epic_created"
    EPIC_DELETED = "epic_deleted"
    FEATURE_CREATED = "feature_created"
    FEATURE_DELETED = "feature_deleted"
    TASK_CREATED = "task_created"
    TASK_DELETED = "task_deleted"
    TASK_NOTE_ADDED = "task_note_added"
    BULK_IMPORT = "bulk_import"
```

- [ ] **Step 4: Run test again — still fails (event not emitted yet)**

Run: `uv run pytest tests/board/test_routes.py::test_create_epic_emits_event -v`
Expected: FAIL — `mock_publish.assert_called_once()` fails because the route doesn't emit yet.

- [ ] **Step 5: Commit enum changes**

```bash
git add src/shared/events.py tests/board/test_routes.py
git commit -m "feat(events): add 8 new SSE event types for board CRUD operations"
```

---

### Task 2: Emit events from board create routes

**Files:**
- Modify: `src/board/routes.py:82-99` (create_epic), `src/board/routes.py:123-133` (create_feature), `src/board/routes.py:162-172` (create_task)
- Test: `tests/board/test_routes.py`

- [ ] **Step 1: Add event emission to create_epic**

In `src/board/routes.py`, modify `create_epic` to emit after creation. Add before the `return` statement at line 99:

```python
    await event_bus.publish(
        Event(
            type=EventType.EPIC_CREATED,
            project_id=project_id,
            data={"epic_id": str(epic.id), "title": body.title},
        )
    )
    return EpicResponse.model_validate(epic)
```

- [ ] **Step 2: Run the test from Task 1 to verify it passes**

Run: `uv run pytest tests/board/test_routes.py::test_create_epic_emits_event -v`
Expected: PASS

- [ ] **Step 3: Write tests for create_feature and create_task events**

Add to `tests/board/test_routes.py`:

```python
async def test_create_feature_emits_event(client: AsyncClient):
    """Creating a feature emits a FEATURE_CREATED event."""
    project = (await client.post("/api/v1/projects", json={"name": "feat-event-test"})).json()
    epic = (
        await client.post(f"/api/v1/projects/{project['id']}/epics", json={"title": "Epic"})
    ).json()

    with patch("src.board.routes.event_bus.publish", new_callable=AsyncMock) as mock_publish:
        resp = await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "New Feature"},
        )
        assert resp.status_code == 201
        mock_publish.assert_called_once()
        event = mock_publish.call_args[0][0]
        assert event.type == "feature_created"
        assert str(event.project_id) == project["id"]
        assert event.data["title"] == "New Feature"


async def test_create_task_emits_event(client: AsyncClient):
    """Creating a task emits a TASK_CREATED event."""
    project = (await client.post("/api/v1/projects", json={"name": "task-event-test"})).json()
    epic = (
        await client.post(f"/api/v1/projects/{project['id']}/epics", json={"title": "Epic"})
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "Feature"},
        )
    ).json()

    with patch("src.board.routes.event_bus.publish", new_callable=AsyncMock) as mock_publish:
        resp = await client.post(
            f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
            json={"title": "New Task"},
        )
        assert resp.status_code == 201
        mock_publish.assert_called_once()
        event = mock_publish.call_args[0][0]
        assert event.type == "task_created"
        assert str(event.project_id) == project["id"]
        assert event.data["title"] == "New Task"
```

- [ ] **Step 4: Run new tests to verify they fail**

Run: `uv run pytest tests/board/test_routes.py::test_create_feature_emits_event tests/board/test_routes.py::test_create_task_emits_event -v`
Expected: FAIL — events not emitted yet.

- [ ] **Step 5: Add event emission to create_feature**

In `src/board/routes.py`, modify `create_feature`. The `epic` is already loaded at line 126. Add before the return:

```python
    await event_bus.publish(
        Event(
            type=EventType.FEATURE_CREATED,
            project_id=epic.project_id,
            data={"feature_id": str(feature.id), "title": body.title},
        )
    )
    return FeatureResponse.model_validate(feature)
```

- [ ] **Step 6: Add event emission to create_task**

In `src/board/routes.py`, modify `create_task`. The `feature` is already loaded at line 165. Need to also load the epic to get `project_id`. Add after the `create_task` call:

```python
    epic = await service._repo.get_epic(feature.epic_id)
    assert epic is not None
    await event_bus.publish(
        Event(
            type=EventType.TASK_CREATED,
            project_id=epic.project_id,
            data={"task_id": str(task.id), "title": body.title},
        )
    )
    return TaskResponse.model_validate(task)
```

- [ ] **Step 7: Run all new tests**

Run: `uv run pytest tests/board/test_routes.py::test_create_epic_emits_event tests/board/test_routes.py::test_create_feature_emits_event tests/board/test_routes.py::test_create_task_emits_event -v`
Expected: PASS (3 tests)

- [ ] **Step 8: Commit**

```bash
git add src/board/routes.py tests/board/test_routes.py
git commit -m "feat(events): emit SSE events on epic/feature/task creation"
```

---

### Task 3: Emit events from board delete routes

**Files:**
- Modify: `src/board/routes.py:108-112` (delete_epic), `src/board/routes.py:147-151` (delete_feature), `src/board/routes.py:209-213` (delete_task)
- Test: `tests/board/test_routes.py`

- [ ] **Step 1: Write tests for all three delete events**

Add to `tests/board/test_routes.py`:

```python
async def test_delete_epic_emits_event(client: AsyncClient):
    """Deleting an epic emits an EPIC_DELETED event."""
    project = (await client.post("/api/v1/projects", json={"name": "del-epic-test"})).json()
    epic = (
        await client.post(f"/api/v1/projects/{project['id']}/epics", json={"title": "Epic"})
    ).json()

    with patch("src.board.routes.event_bus.publish", new_callable=AsyncMock) as mock_publish:
        resp = await client.delete(f"/api/v1/epics/{epic['id']}")
        assert resp.status_code == 204
        mock_publish.assert_called_once()
        event = mock_publish.call_args[0][0]
        assert event.type == "epic_deleted"
        assert str(event.project_id) == project["id"]
        assert event.data["epic_id"] == epic["id"]


async def test_delete_feature_emits_event(client: AsyncClient):
    """Deleting a feature emits a FEATURE_DELETED event."""
    project = (await client.post("/api/v1/projects", json={"name": "del-feat-test"})).json()
    epic = (
        await client.post(f"/api/v1/projects/{project['id']}/epics", json={"title": "Epic"})
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "Feature"},
        )
    ).json()

    with patch("src.board.routes.event_bus.publish", new_callable=AsyncMock) as mock_publish:
        resp = await client.delete(f"/api/v1/features/{feature['id']}")
        assert resp.status_code == 204
        mock_publish.assert_called_once()
        event = mock_publish.call_args[0][0]
        assert event.type == "feature_deleted"
        assert str(event.project_id) == project["id"]
        assert event.data["feature_id"] == feature["id"]


async def test_delete_task_emits_event(client: AsyncClient):
    """Deleting a task emits a TASK_DELETED event."""
    project = (await client.post("/api/v1/projects", json={"name": "del-task-test"})).json()
    epic = (
        await client.post(f"/api/v1/projects/{project['id']}/epics", json={"title": "Epic"})
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "Feature"},
        )
    ).json()
    task = (
        await client.post(
            f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
            json={"title": "Task"},
        )
    ).json()

    with patch("src.board.routes.event_bus.publish", new_callable=AsyncMock) as mock_publish:
        resp = await client.delete(f"/api/v1/tasks/{task['id']}")
        assert resp.status_code == 204
        mock_publish.assert_called_once()
        event = mock_publish.call_args[0][0]
        assert event.type == "task_deleted"
        assert str(event.project_id) == project["id"]
        assert event.data["task_id"] == task["id"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/board/test_routes.py -k "delete.*emits" -v`
Expected: FAIL (3 tests)

- [ ] **Step 3: Implement delete_epic event emission**

In `src/board/routes.py`, modify `delete_epic`. Must capture `project_id` before deleting:

```python
@router.delete("/epics/{epic_id}", status_code=204)
async def delete_epic(epic_id: UUID, service: ServiceDep) -> None:
    epic = await service._repo.get_epic(epic_id)
    if epic is None:
        raise HTTPException(status_code=404, detail="Epic not found")
    project_id = epic.project_id
    deleted = await service._repo.delete_epic(epic_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Epic not found")
    await event_bus.publish(
        Event(
            type=EventType.EPIC_DELETED,
            project_id=project_id,
            data={"epic_id": str(epic_id)},
        )
    )
```

- [ ] **Step 4: Implement delete_feature event emission**

```python
@router.delete("/features/{feature_id}", status_code=204)
async def delete_feature(feature_id: UUID, service: ServiceDep) -> None:
    feature = await service._repo.get_feature(feature_id)
    if feature is None:
        raise HTTPException(status_code=404, detail="Feature not found")
    epic = await service._repo.get_epic(feature.epic_id)
    assert epic is not None
    project_id = epic.project_id
    deleted = await service._repo.delete_feature(feature_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Feature not found")
    await event_bus.publish(
        Event(
            type=EventType.FEATURE_DELETED,
            project_id=project_id,
            data={"feature_id": str(feature_id)},
        )
    )
```

- [ ] **Step 5: Implement delete_task event emission**

```python
@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(task_id: UUID, service: ServiceDep) -> None:
    task = await service._repo.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    feature = await service._repo.get_feature(task.feature_id)
    assert feature is not None
    epic = await service._repo.get_epic(feature.epic_id)
    assert epic is not None
    project_id = epic.project_id
    deleted = await service._repo.delete_task(task_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Task not found")
    await event_bus.publish(
        Event(
            type=EventType.TASK_DELETED,
            project_id=project_id,
            data={"task_id": str(task_id)},
        )
    )
```

- [ ] **Step 6: Run delete event tests**

Run: `uv run pytest tests/board/test_routes.py -k "delete.*emits" -v`
Expected: PASS (3 tests)

- [ ] **Step 7: Commit**

```bash
git add src/board/routes.py tests/board/test_routes.py
git commit -m "feat(events): emit SSE events on epic/feature/task deletion"
```

---

### Task 4: Emit events from document and agent routes

**Files:**
- Modify: `src/document/routes.py:26-35`
- Modify: `src/agent/routes.py:94-107`
- Modify: `src/board/routes.py:321-326` (import)
- Test: `tests/e2e/test_document_events.py`, `tests/board/test_routes.py`

- [ ] **Step 1: Write test for document_attached event**

Create `tests/e2e/test_document_events.py`. Use the e2e client which has all routers mounted — this avoids raw DB manipulation and creates entities through the API:

```python
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient


async def test_create_document_emits_event(client: AsyncClient):
    """Attaching a document emits a DOCUMENT_ATTACHED event."""
    project = (await client.post("/api/v1/projects", json={"name": "doc-event-test"})).json()
    epic = (
        await client.post(f"/api/v1/projects/{project['id']}/epics", json={"title": "Epic"})
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "Feature"},
        )
    ).json()

    with patch("src.document.routes.event_bus.publish", new_callable=AsyncMock) as mock_publish:
        resp = await client.post(
            "/api/v1/documents",
            json={
                "title": "Spec",
                "content": "# Spec content",
                "doc_type": "spec",
                "source_path": "",
                "attached_to_type": "feature",
                "attached_to_id": feature["id"],
            },
        )
        assert resp.status_code == 201
        mock_publish.assert_called_once()
        event = mock_publish.call_args[0][0]
        assert event.type == "document_attached"
        assert str(event.project_id) == project["id"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/e2e/test_document_events.py::test_create_document_emits_event -v`
Expected: FAIL

- [ ] **Step 3: Implement document_attached event with project_id resolver**

In `src/document/routes.py`, add the imports and resolver helper, then emit the event:

```python
from src.board.repository import BoardRepository
from src.shared.events import Event, EventType, event_bus


async def _resolve_project_id(
    attached_to_type: str, attached_to_id: UUID, board_repo: BoardRepository
) -> UUID | None:
    """Walk up the entity chain to find the project_id."""
    if attached_to_type == "epic":
        epic = await board_repo.get_epic(attached_to_id)
        return epic.project_id if epic else None
    if attached_to_type == "feature":
        feature = await board_repo.get_feature(attached_to_id)
        if feature is None:
            return None
        epic = await board_repo.get_epic(feature.epic_id)
        return epic.project_id if epic else None
    if attached_to_type == "task":
        task = await board_repo.get_task(attached_to_id)
        if task is None:
            return None
        feature = await board_repo.get_feature(task.feature_id)
        if feature is None:
            return None
        epic = await board_repo.get_epic(feature.epic_id)
        return epic.project_id if epic else None
    return None
```

Then modify `create_document` to accept a session dependency and emit:

```python
@router.post("/documents", response_model=DocumentResponse, status_code=201)
async def create_document(
    body: DocumentCreate,
    service: ServiceDep,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    result = await service.create_document(
        title=body.title,
        content=body.content,
        doc_type=body.doc_type,
        source_path=body.source_path,
        attached_to_type=body.attached_to_type,
        attached_to_id=body.attached_to_id,
    )
    if body.attached_to_id is not None:
        board_repo = BoardRepository(session)
        project_id = await _resolve_project_id(
            body.attached_to_type, body.attached_to_id, board_repo
        )
        if project_id is not None:
            await event_bus.publish(
                Event(
                    type=EventType.DOCUMENT_ATTACHED,
                    project_id=project_id,
                    data={
                        "document_id": str(result["id"]),
                        "attached_to_type": body.attached_to_type,
                        "attached_to_id": str(body.attached_to_id),
                    },
                )
            )
    return result
```

- [ ] **Step 4: Run document test**

Run: `uv run pytest tests/e2e/test_document_events.py::test_create_document_emits_event -v`
Expected: PASS

- [ ] **Step 5: Write and implement task_note_added event**

In `src/agent/routes.py`, modify the `add_task_note` handler. The task is already loaded at line 98. Need to walk up to get `project_id`:

```python
@router.post("/agents/{worktree_id}/task-note", status_code=201)
async def add_task_note(
    worktree_id: UUID, body: AddTaskNoteRequest, service: ServiceDep
) -> dict[str, object]:
    task = await service._board_repo.get_task(body.task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    note = await service._board_repo.add_task_note(body.task_id, body.note)
    feature = await service._board_repo.get_feature(task.feature_id)
    assert feature is not None
    epic = await service._board_repo.get_epic(feature.epic_id)
    assert epic is not None
    await event_bus.publish(
        Event(
            type=EventType.TASK_NOTE_ADDED,
            project_id=epic.project_id,
            data={"task_id": str(body.task_id)},
        )
    )
    return {
        "id": note.id,
        "task_id": note.task_id,
        "note": note.note,
        "created_at": note.created_at,
    }
```

Add the import at the top of `src/agent/routes.py`:

```python
from src.shared.events import Event, EventType, event_bus
```

Also need to add the import for `get_epic` access — the agent service already has `_board_repo` which is a `BoardRepository`, so `get_epic` is available.

- [ ] **Step 6: Write and implement bulk_import event**

In `src/board/routes.py`, modify `import_plan`:

```python
@router.post("/projects/{project_id}/import", status_code=201)
async def import_plan(project_id: UUID, body: ImportPlan, service: ServiceDep) -> dict[str, int]:
    project = await service._repo.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    result = await service.import_plan(project_id, body)
    await event_bus.publish(
        Event(
            type=EventType.BULK_IMPORT,
            project_id=project_id,
            data={
                "epics_created": result["epics"],
                "features_created": result["features"],
                "tasks_created": result["tasks"],
            },
        )
    )
    return result
```

- [ ] **Step 7: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: All pass (138 existing + new event tests)

- [ ] **Step 8: Commit**

```bash
git add src/document/routes.py src/agent/routes.py src/board/routes.py tests/e2e/test_document_events.py
git commit -m "feat(events): emit document_attached, task_note_added, bulk_import events"
```

---

### Task 5: Update frontend SSE listener

**Files:**
- Modify: `frontend/src/hooks/useSSE.ts:18-23`
- Modify: `frontend/src/api/types.ts:49-51`

- [ ] **Step 1: Update SSEEvent type**

In `frontend/src/api/types.ts`, update the type union:

```typescript
export type SSEEvent = {
  type:
    | 'task_status_changed'
    | 'worktree_online'
    | 'worktree_offline'
    | 'document_attached'
    | 'epic_created'
    | 'epic_deleted'
    | 'feature_created'
    | 'feature_deleted'
    | 'task_created'
    | 'task_deleted'
    | 'task_note_added'
    | 'bulk_import'
  data: Record<string, string>
}
```

- [ ] **Step 2: Update useSSE listener array**

In `frontend/src/hooks/useSSE.ts`, replace the `eventTypes` array:

```typescript
    const eventTypes = [
      'task_status_changed',
      'worktree_online',
      'worktree_offline',
      'document_attached',
      'epic_created',
      'epic_deleted',
      'feature_created',
      'feature_deleted',
      'task_created',
      'task_deleted',
      'task_note_added',
      'bulk_import',
    ] as const
```

- [ ] **Step 3: Run frontend tests**

Run: `cd frontend && npx vitest run`
Expected: All 107 tests pass. The `useBoard.ts` handler already refetches on unknown event types via the `else` fallback — no changes needed there.

- [ ] **Step 4: Run full backend tests to confirm nothing broke**

Run: `uv run pytest tests/ -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useSSE.ts frontend/src/api/types.ts
git commit -m "feat(frontend): listen for all new SSE event types"
```

---

### Task 6: Final integration verification

- [ ] **Step 1: Run full quality gate**

Run: `make lint && make typecheck && uv run pytest && cd frontend && npx vitest run`
Expected: All green

- [ ] **Step 2: Manual smoke test**

Start the dev server (`make run-backend` + `cd frontend && npm run dev`), open the board in browser, then create an epic via curl or MCP — the backlog should update without page refresh.

- [ ] **Step 3: Final commit if any adjustments needed, then push**

```bash
git push origin HEAD
```
