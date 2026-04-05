# F-20: Drag-and-Drop Backlog Prioritization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable users to reorder epics, features, and tasks in the backlog tree by dragging them. Changes persist to the backend and broadcast via SSE for real-time updates.

**Architecture:** Three new batch reorder endpoints in the Board context. @dnd-kit library for the frontend drag interaction. Optimistic UI with revert on failure.

**Tech Stack:** Python/FastAPI (backend), React + @dnd-kit (frontend), TypeScript

**Design Spec:** `docs/superpowers/specs/2026-04-05-drag-drop-backlog-design.md`

---

### Task 1: Backend — Add reorder repository methods

**Files:**
- Modify: `src/board/repository.py`
- Test: `tests/board/test_repository.py`

- [ ] **Step 1: Write failing tests**

Add tests to `tests/board/test_repository.py`:

```python
async def test_reorder_epics(self, db_session):
    """Verify batch position update for epics within a project."""
    repo = BoardRepository(db_session)
    project = await repo.create_project("test", "", "")
    e1 = await repo.create_epic(project.id, "E1", "", "", "", 0, number=1)
    e2 = await repo.create_epic(project.id, "E2", "", "", "", 1, number=2)
    e3 = await repo.create_epic(project.id, "E3", "", "", "", 2, number=3)
    
    # Reorder: E3 first, E1 second, E2 third
    await repo.reorder_epics(project.id, [
        (e3.id, 0), (e1.id, 1000), (e2.id, 2000)
    ])
    
    epics = await repo.list_epics(project.id)
    assert [e.id for e in epics] == [e3.id, e1.id, e2.id]

async def test_reorder_features(self, db_session):
    """Verify batch position update for features within an epic."""
    repo = BoardRepository(db_session)
    project = await repo.create_project("test", "", "")
    epic = await repo.create_epic(project.id, "E1", "", "", "", 0, number=1)
    f1 = await repo.create_feature(epic.id, "F1", "", 0, number=1)
    f2 = await repo.create_feature(epic.id, "F2", "", 1, number=2)
    
    await repo.reorder_features(epic.id, [(f2.id, 0), (f1.id, 1000)])
    
    features = await repo.list_features(epic.id)
    assert [f.id for f in features] == [f2.id, f1.id]

async def test_reorder_tasks(self, db_session):
    """Verify batch position update for tasks within a feature."""
    repo = BoardRepository(db_session)
    project = await repo.create_project("test", "", "")
    epic = await repo.create_epic(project.id, "E1", "", "", "", 0, number=1)
    feature = await repo.create_feature(epic.id, "F1", "", 0, number=1)
    t1 = await repo.create_task(feature.id, "T1", "", "normal", 0, number=1)
    t2 = await repo.create_task(feature.id, "T2", "", "normal", 1, number=2)
    t3 = await repo.create_task(feature.id, "T3", "", "normal", 2, number=3)
    
    await repo.reorder_tasks(feature.id, [
        (t3.id, 0), (t2.id, 1000), (t1.id, 2000)
    ])
    
    tasks = await repo.get_tasks_for_feature(feature.id)
    assert [t.id for t in tasks] == [t3.id, t2.id, t1.id]

async def test_reorder_epics_invalid_id(self, db_session):
    """Reorder with a non-existent ID should raise ValueError."""
    repo = BoardRepository(db_session)
    project = await repo.create_project("test", "", "")
    import uuid
    with pytest.raises(ValueError):
        await repo.reorder_epics(project.id, [(uuid.uuid4(), 0)])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test-board` — expect failures for missing methods.

- [ ] **Step 3: Implement repository methods**

In `src/board/repository.py`, add three methods:

```python
async def reorder_epics(self, project_id: UUID, positions: list[tuple[UUID, int]]) -> None:
    """Batch update epic positions. Validates all IDs belong to the project."""
    epic_ids = [eid for eid, _ in positions]
    result = await self._session.execute(
        select(Epic).where(Epic.project_id == project_id, Epic.id.in_(epic_ids))
    )
    epics = {e.id: e for e in result.scalars().all()}
    if len(epics) != len(positions):
        raise ValueError("One or more epic IDs not found in this project")
    for epic_id, position in positions:
        epics[epic_id].position = position
    await self._session.commit()

async def reorder_features(self, epic_id: UUID, positions: list[tuple[UUID, int]]) -> None:
    """Batch update feature positions within an epic."""
    feat_ids = [fid for fid, _ in positions]
    result = await self._session.execute(
        select(Feature).where(Feature.epic_id == epic_id, Feature.id.in_(feat_ids))
    )
    features = {f.id: f for f in result.scalars().all()}
    if len(features) != len(positions):
        raise ValueError("One or more feature IDs not found in this epic")
    for feat_id, position in positions:
        features[feat_id].position = position
    await self._session.commit()

async def reorder_tasks(self, feature_id: UUID, positions: list[tuple[UUID, int]]) -> None:
    """Batch update task positions within a feature."""
    task_ids = [tid for tid, _ in positions]
    result = await self._session.execute(
        select(Task).where(Task.feature_id == feature_id, Task.id.in_(task_ids))
    )
    tasks = {t.id: t for t in result.scalars().all()}
    if len(tasks) != len(positions):
        raise ValueError("One or more task IDs not found in this feature")
    for task_id, position in positions:
        tasks[task_id].position = position
    await self._session.commit()
```

- [ ] **Step 4: Run tests — all should pass**

Run: `make test-board`

---

### Task 2: Backend — Add reorder schemas and API endpoints

**Files:**
- Modify: `src/board/schemas.py`
- Modify: `src/board/routes.py`
- Modify: `src/shared/events.py`
- Test: `tests/board/test_routes.py`

- [ ] **Step 1: Add schemas**

In `src/board/schemas.py`, add:

```python
class ReorderItem(BaseModel):
    id: UUID
    position: int

class ReorderRequest(BaseModel):
    items: list[ReorderItem]
```

- [ ] **Step 2: Add SSE event types**

In `src/shared/events.py`, add to `EventType`:

```python
EPIC_REORDERED = "epic_reordered"
FEATURE_REORDERED = "feature_reordered"
TASK_REORDERED = "task_reordered"
```

- [ ] **Step 3: Write failing route tests**

In `tests/board/test_routes.py`, add integration tests:

```python
async def test_reorder_epics(client, project_id, epic_ids):
    """POST /projects/{id}/epics/reorder updates positions."""
    resp = await client.post(
        f"/api/v1/projects/{project_id}/epics/reorder",
        json={"items": [
            {"id": str(epic_ids[1]), "position": 0},
            {"id": str(epic_ids[0]), "position": 1000},
        ]},
    )
    assert resp.status_code == 200
    # Verify new order via backlog
    backlog = await client.get(f"/api/v1/projects/{project_id}/backlog")
    assert backlog.json()[0]["epic"]["id"] == str(epic_ids[1])

async def test_reorder_features(client, project_id, epic_id, feature_ids):
    """POST /projects/{id}/epics/{id}/features/reorder updates positions."""
    resp = await client.post(
        f"/api/v1/projects/{project_id}/epics/{epic_id}/features/reorder",
        json={"items": [
            {"id": str(feature_ids[1]), "position": 0},
            {"id": str(feature_ids[0]), "position": 1000},
        ]},
    )
    assert resp.status_code == 200

async def test_reorder_tasks(client, feature_id, task_ids):
    """POST /features/{id}/tasks/reorder updates positions."""
    resp = await client.post(
        f"/api/v1/features/{feature_id}/tasks/reorder",
        json={"items": [
            {"id": str(task_ids[1]), "position": 0},
            {"id": str(task_ids[0]), "position": 1000},
        ]},
    )
    assert resp.status_code == 200

async def test_reorder_invalid_ids(client, project_id):
    """Reorder with invalid IDs returns 400."""
    import uuid
    resp = await client.post(
        f"/api/v1/projects/{project_id}/epics/reorder",
        json={"items": [{"id": str(uuid.uuid4()), "position": 0}]},
    )
    assert resp.status_code == 400
```

- [ ] **Step 4: Implement route endpoints**

In `src/board/routes.py`, add three reorder endpoints:

```python
@router.post("/projects/{project_id}/epics/reorder")
async def reorder_epics(
    project_id: UUID, body: ReorderRequest, service: ServiceDep
) -> dict[str, str]:
    try:
        await service._repo.reorder_epics(
            project_id, [(item.id, item.position) for item in body.items]
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await event_bus.publish(
        Event(type=EventType.EPIC_REORDERED, project_id=project_id, data={})
    )
    return {"status": "ok"}

@router.post("/projects/{project_id}/epics/{epic_id}/features/reorder")
async def reorder_features(
    project_id: UUID, epic_id: UUID, body: ReorderRequest, service: ServiceDep
) -> dict[str, str]:
    try:
        await service._repo.reorder_features(
            epic_id, [(item.id, item.position) for item in body.items]
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await event_bus.publish(
        Event(type=EventType.FEATURE_REORDERED, project_id=project_id, data={"epic_id": str(epic_id)})
    )
    return {"status": "ok"}

@router.post("/features/{feature_id}/tasks/reorder")
async def reorder_tasks(
    feature_id: UUID, body: ReorderRequest, service: ServiceDep
) -> dict[str, str]:
    feature = await service._repo.get_feature(feature_id)
    if feature is None:
        raise HTTPException(status_code=404, detail="Feature not found")
    epic = await service._repo.get_epic(feature.epic_id)
    assert epic is not None
    try:
        await service._repo.reorder_tasks(
            feature_id, [(item.id, item.position) for item in body.items]
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await event_bus.publish(
        Event(type=EventType.TASK_REORDERED, project_id=epic.project_id, data={"feature_id": str(feature_id)})
    )
    return {"status": "ok"}
```

Remember to import `ReorderRequest` in the routes file.

- [ ] **Step 5: Run tests — all should pass**

Run: `make test-board`

---

### Task 3: Contract — Update OpenAPI spec and regenerate types

**Files:**
- Modify: `docs/contracts/baseline.openapi.yaml`
- Regenerate: `frontend/src/api/generated-types.ts`

- [ ] **Step 1: Add reorder schemas and endpoints to OpenAPI**

Add `ReorderItem` and `ReorderRequest` schemas. Add three reorder endpoint paths:
- `POST /projects/{project_id}/epics/reorder`
- `POST /projects/{project_id}/epics/{epic_id}/features/reorder`
- `POST /features/{feature_id}/tasks/reorder`

Each accepts `ReorderRequest` body and returns `{"status": "ok"}`.

- [ ] **Step 2: Regenerate frontend types**

Run: `./scripts/generate-contract-types.sh docs/contracts/baseline.openapi.yaml`

- [ ] **Step 3: Run contract check**

Run: `make contract-check` — verify backend matches updated contract.

---

### Task 4: Frontend — Install @dnd-kit and add API client methods

**Files:**
- Modify: `frontend/package.json` (via npm install)
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/types.ts` (if needed for new types)

- [ ] **Step 1: Install @dnd-kit**

```bash
cd frontend && npm install @dnd-kit/core @dnd-kit/sortable @dnd-kit/utilities
```

Verify it appears in `package.json` dependencies. Check existing tests still pass: `cd frontend && make test`

- [ ] **Step 2: Add reorder API methods to client.ts**

```typescript
// Reorder
reorderEpics: (projectId: string, items: { id: string; position: number }[]) =>
  fetchJSON(`/projects/${projectId}/epics/reorder`, {
    method: 'POST',
    body: JSON.stringify({ items }),
  }),

reorderFeatures: (projectId: string, epicId: string, items: { id: string; position: number }[]) =>
  fetchJSON(`/projects/${projectId}/epics/${epicId}/features/reorder`, {
    method: 'POST',
    body: JSON.stringify({ items }),
  }),

reorderTasks: (featureId: string, items: { id: string; position: number }[]) =>
  fetchJSON(`/features/${featureId}/tasks/reorder`, {
    method: 'POST',
    body: JSON.stringify({ items }),
  }),
```

---

### Task 5: Frontend — Add drag-and-drop to BacklogTree

**Files:**
- Modify: `frontend/src/components/BacklogTree.tsx`
- Modify: `frontend/src/components/BacklogTree.css`
- Create: `frontend/src/components/SortableItem.tsx` (reusable drag wrapper)
- Test: `frontend/src/components/BacklogTree.test.tsx`

This is the largest task. It modifies the BacklogTree component to support DnD.

- [ ] **Step 1: Create SortableItem component**

Create `frontend/src/components/SortableItem.tsx` — a thin wrapper that:
- Uses `useSortable` from `@dnd-kit/sortable`
- Renders a drag handle (grip dots icon via CSS)
- Passes through children
- Applies transform/transition styles from dnd-kit

```tsx
import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'

interface SortableItemProps {
  id: string
  children: React.ReactNode
  handle?: boolean
}

export function SortableItem({ id, children }: SortableItemProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id })
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  }
  return (
    <div ref={setNodeRef} style={style} {...attributes}>
      <span className="drag-handle" {...listeners}>⠿</span>
      {children}
    </div>
  )
}
```

- [ ] **Step 2: Add drag handle CSS**

In `BacklogTree.css`, add styles for:
- `.drag-handle` — grip dots icon, hidden by default, shown on row hover
- `.drag-handle:hover` — cursor: grab
- `.dragging` state — shadow + slight scale
- Drop placeholder line styling
- Touch device override (always show handles)

- [ ] **Step 3: Wrap BacklogTree with DnD contexts**

Modify `BacklogTree.tsx`:
1. Import `DndContext`, `SortableContext`, `closestCenter`, `restrictToVerticalAxis`, sensors
2. Configure `PointerSensor` (mouse) with `activationConstraint: { distance: 5 }` and `TouchSensor` with `activationConstraint: { delay: 200, tolerance: 5 }`
3. Wrap each level in a `<SortableContext>`:
   - Epic list: sortable among visible epics
   - Feature list (per epic): sortable among features in that epic
   - Task list (per feature): sortable among tasks in that feature
4. Each item becomes a `<SortableItem>` with drag handle
5. Keep existing click handlers for navigation (they fire on the title, not the drag handle)

- [ ] **Step 4: Add onDragEnd handler**

The `onDragEnd` handler needs to:
1. Determine which level was dragged (epic/feature/task) — use `active.data.current.type` set during `<SortableItem>` setup
2. Calculate new positions: assign `index * 1000` to each item in the new order
3. Optimistically update local state (reorder the array)
4. Call the appropriate reorder API method
5. On failure: revert to previous state, log error

- [ ] **Step 5: Pass reorder callbacks from parent**

The `BacklogTree` component needs new props:
```typescript
interface BacklogTreeProps {
  backlog: BacklogEpic[]
  onItemClick: (type: 'epic' | 'feature' | 'task', id: string) => void
  onReorderEpics?: (items: { id: string; position: number }[]) => void
  onReorderFeatures?: (epicId: string, items: { id: string; position: number }[]) => void
  onReorderTasks?: (featureId: string, items: { id: string; position: number }[]) => void
}
```

In `Board.tsx`, wire these to the API client methods and handle optimistic state updates.

- [ ] **Step 6: Write component tests**

In `frontend/src/components/BacklogTree.test.tsx`:

```typescript
describe('BacklogTree drag-and-drop', () => {
  it('renders drag handles for each epic', () => {
    render(<BacklogTree backlog={mockBacklog} onItemClick={vi.fn()} />)
    const handles = screen.getAllByLabelText(/reorder/i)
    expect(handles.length).toBeGreaterThan(0)
  })

  it('still navigates on title click (not drag handle)', () => {
    const onClick = vi.fn()
    render(<BacklogTree backlog={mockBacklog} onItemClick={onClick} />)
    fireEvent.click(screen.getByText('Epic 1'))
    expect(onClick).toHaveBeenCalledWith('epic', expect.any(String))
  })

  it('calls onReorderEpics after drag', async () => {
    // Use @dnd-kit testing utilities or simulate drag events
    // Verify callback is called with new positions
  })
})
```

- [ ] **Step 7: Run frontend tests**

Run: `cd frontend && make test`

---

### Task 6: Frontend — SSE integration for reorder events

**Files:**
- Modify: `frontend/src/hooks/useBoard.ts`

- [ ] **Step 1: Handle reorder SSE events**

In `useBoard.ts`, update the `handleSSE` callback to handle the new event types:

```typescript
} else if (
  event.type === 'epic_reordered' ||
  event.type === 'feature_reordered' ||
  event.type === 'task_reordered'
) {
  // Refetch backlog to get updated order
  // This is simpler than applying position deltas client-side
  api.getBacklog(projectId!).then(setBacklog)
}
```

Note: The existing else branch already calls `fetchBoard()` which refetches everything. The reorder events will be caught by that branch. However, for efficiency, we should handle them specifically to only refetch the backlog (not the full board). Add the specific handler above the generic else.

- [ ] **Step 2: Test SSE handling**

Verify that when a reorder event arrives, the backlog updates without a full page refresh. Manual testing via the running app is sufficient here since SSE testing is integration-level.

---

### Task 7: Quality gate and cleanup

**Files:**
- All modified files

- [ ] **Step 1: Run full quality gate**

```bash
make quality
```

Fix any lint, type, or test failures.

- [ ] **Step 2: Verify contract compliance**

```bash
make contract-check
```

- [ ] **Step 3: Manual smoke test**

Start the app (`make run-backend` + `cd frontend && npm run dev`), open the board, and verify:
1. Drag handles appear on hover
2. Epics can be reordered
3. Features within an epic can be reordered
4. Tasks within a feature can be reordered
5. Order persists after page refresh
6. SSE updates work (open two browser tabs)

---

## Execution Notes

- **Task 1-2** are backend-only and can be done in one subagent
- **Task 3** (contract update) should be done after Task 2 since the endpoints must exist first
- **Task 4** (frontend deps + API client) is independent of Tasks 1-3 and can be done in parallel
- **Task 5** (BacklogTree DnD) depends on Task 4 (needs @dnd-kit installed and API methods)
- **Task 6** (SSE) depends on Task 2 (needs event types) and Task 5 (needs the component)
- **Task 7** is final validation

**Parallelization:** Tasks 1+2 (backend) and Task 4 (frontend deps) can run in parallel subagents. Task 3 follows backend. Tasks 5+6 follow both. Task 7 is serial.
