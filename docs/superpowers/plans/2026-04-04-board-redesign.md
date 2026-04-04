# Board Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat Kanban board with a grouped backlog (Epic > Feature > Task tree) + flat flow columns with breadcrumb pills, a multi-level detail panel, and blocked card treatment.

**Architecture:** Add `color` field to Epic model, new `/backlog` API endpoint returning the tree, `epic_color` on board task response. Frontend gets new components: BacklogTree, BreadcrumbPills, DetailPanel. Existing Board/Column/TaskCard components are modified.

**Tech Stack:** Python/FastAPI/SQLAlchemy (backend), React/TypeScript (frontend), Alembic (migration)

---

### Task 1: Add color field to Epic model + migration

**Files:**
- Modify: `src/board/models.py:32-52`
- Modify: `src/board/schemas.py:46-65`
- Modify: `src/board/repository.py:48-68`
- Modify: `src/board/services.py:83-123`
- Create: `src/alembic/versions/xxxx_add_epic_color.py` (via autogenerate)
- Test: `tests/board/test_routes.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/board/test_routes.py`:

```python
async def test_create_epic_auto_assigns_color(client: AsyncClient):
    project = (await client.post("/api/v1/projects", json={"name": "color-test"})).json()
    epic = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics",
            json={"title": "Epic 1"},
        )
    ).json()
    assert "color" in epic
    assert epic["color"].startswith("#")
    assert len(epic["color"]) == 7


async def test_epics_get_distinct_colors(client: AsyncClient):
    project = (await client.post("/api/v1/projects", json={"name": "multi-color"})).json()
    colors = []
    for i in range(4):
        epic = (
            await client.post(
                f"/api/v1/projects/{project['id']}/epics",
                json={"title": f"Epic {i}"},
            )
        ).json()
        colors.append(epic["color"])
    # First 4 should all be distinct
    assert len(set(colors)) == 4
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/board/test_routes.py::test_create_epic_auto_assigns_color tests/board/test_routes.py::test_epics_get_distinct_colors -v`
Expected: FAIL — `color` not in response

- [ ] **Step 3: Add color to Epic model**

In `src/board/models.py`, add to the `Epic` class after the `position` field:

```python
    color: Mapped[str] = mapped_column(String(7), default="")
```

- [ ] **Step 4: Add color to EpicResponse schema**

In `src/board/schemas.py`, add to `EpicResponse`:

```python
    color: str
```

- [ ] **Step 5: Add color palette and auto-assignment to service**

In `src/board/services.py`, add a palette constant and update `import_plan`:

```python
EPIC_COLOR_PALETTE = [
    "#7c3aed",  # purple
    "#0ea5e9",  # cyan
    "#f59e0b",  # amber
    "#10b981",  # emerald
    "#ef4444",  # red
    "#ec4899",  # pink
    "#6366f1",  # indigo
    "#14b8a6",  # teal
    "#f97316",  # orange
    "#8b5cf6",  # violet
]
```

In `src/board/repository.py`, add a method to count epics for a project:

```python
    async def count_epics(self, project_id: UUID) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(Epic).where(Epic.project_id == project_id)
        )
        return result.scalar_one()
```

Add the `func` import at the top of `repository.py`:

```python
from sqlalchemy import func, select
```

Update `create_epic` in `repository.py` to accept a `color` parameter:

```python
    async def create_epic(
        self,
        project_id: UUID,
        title: str,
        description: str,
        bounded_context: str,
        context_description: str,
        position: int,
        color: str = "",
    ) -> Epic:
        epic = Epic(
            project_id=project_id,
            title=title,
            description=description,
            bounded_context=bounded_context,
            context_description=context_description,
            position=position,
            color=color,
        )
        self._session.add(epic)
        await self._session.commit()
        await self._session.refresh(epic)
        return epic
```

Update `import_plan` in `services.py` to auto-assign colors:

```python
    async def import_plan(self, project_id: UUID, plan: ImportPlan) -> dict[str, int]:
        """Bulk import epics/features/tasks from a structured plan."""
        epics_created = 0
        features_created = 0
        tasks_created = 0

        existing_count = await self._repo.count_epics(project_id)

        for epic_pos, epic_data in enumerate(plan.epics):
            color_index = (existing_count + epic_pos) % len(EPIC_COLOR_PALETTE)
            epic = await self._repo.create_epic(
                project_id=project_id,
                title=epic_data.title,
                description=epic_data.description,
                bounded_context=epic_data.bounded_context,
                context_description="",
                position=epic_pos,
                color=EPIC_COLOR_PALETTE[color_index],
            )
            epics_created += 1

            for feat_pos, feat_data in enumerate(epic_data.features):
                feature = await self._repo.create_feature(
                    epic_id=epic.id,
                    title=feat_data.title,
                    description=feat_data.description,
                    position=feat_pos,
                )
                features_created += 1

                for task_pos, task_data in enumerate(feat_data.tasks):
                    await self._repo.create_task(
                        feature_id=feature.id,
                        title=task_data.title,
                        description=task_data.description,
                        priority=task_data.priority,
                        position=task_pos,
                    )
                    tasks_created += 1

        return {
            "epics_created": epics_created,
            "features_created": features_created,
            "tasks_created": tasks_created,
        }
```

Also update `create_epic` route in `routes.py` to auto-assign color:

```python
@router.post(
    "/projects/{project_id}/epics",
    response_model=EpicResponse,
    status_code=201,
)
async def create_epic(project_id: UUID, body: EpicCreate, service: ServiceDep) -> EpicResponse:
    project = await service._repo.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    existing_count = await service._repo.count_epics(project_id)
    color = EPIC_COLOR_PALETTE[existing_count % len(EPIC_COLOR_PALETTE)]
    epic = await service._repo.create_epic(
        project_id,
        body.title,
        body.description,
        body.bounded_context,
        body.context_description,
        body.position,
        color=color,
    )
    return EpicResponse.model_validate(epic)
```

Add the import at the top of `routes.py`:

```python
from src.board.services import EPIC_COLOR_PALETTE, BoardService
```

- [ ] **Step 6: Generate Alembic migration**

Run: `uv run alembic revision --autogenerate -m "add_epic_color"`

Then edit the generated migration to set a default for existing rows:

```python
def upgrade() -> None:
    op.add_column("epics", sa.Column("color", sa.String(7), nullable=False, server_default=""))
```

Run: `uv run alembic upgrade head`

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/board/test_routes.py -v`
Expected: All pass including the two new tests

- [ ] **Step 8: Commit**

```bash
git add src/board/models.py src/board/schemas.py src/board/repository.py src/board/services.py src/board/routes.py src/alembic/versions/ tests/board/test_routes.py
git commit -m "feat(board): add epic color with auto-assignment from palette"
```

---

### Task 2: Add epic_color to board task response

**Files:**
- Modify: `src/board/schemas.py:126-131`
- Modify: `src/board/routes.py:171-199`
- Test: `tests/board/test_routes.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/board/test_routes.py`:

```python
async def test_board_tasks_include_epic_color(client: AsyncClient):
    project = (await client.post("/api/v1/projects", json={"name": "board-color"})).json()
    epic = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics",
            json={"title": "Colored Epic"},
        )
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "Feature"},
        )
    ).json()
    await client.post(
        f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
        json={"title": "Task"},
    )

    resp = await client.get(f"/api/v1/projects/{project['id']}/board")
    assert resp.status_code == 200
    board = resp.json()
    backlog_tasks = [c for c in board["columns"] if c["status"] == "backlog"][0]["tasks"]
    assert len(backlog_tasks) >= 1
    assert "epic_color" in backlog_tasks[0]
    assert backlog_tasks[0]["epic_color"] == epic["color"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/board/test_routes.py::test_board_tasks_include_epic_color -v`
Expected: FAIL — `epic_color` not in response

- [ ] **Step 3: Add epic_color to TaskCard schema**

In `src/board/schemas.py`, update `TaskCard`:

```python
class TaskCard(TaskResponse):
    """Task with breadcrumb info for the Kanban board."""

    epic_title: str = ""
    feature_title: str = ""
    epic_color: str = ""
```

- [ ] **Step 4: Update board route to include epic_color**

In `src/board/routes.py`, update the `get_board` function's task card construction:

```python
        card = TaskCard(
            **TaskResponse.model_validate(task).model_dump(),
            epic_title=task.feature.epic.title,
            feature_title=task.feature.title,
            epic_color=task.feature.epic.color,
        )
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/board/test_routes.py -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/board/schemas.py src/board/routes.py tests/board/test_routes.py
git commit -m "feat(board): add epic_color to board task card response"
```

---

### Task 3: Create backlog API endpoint

**Files:**
- Modify: `src/board/schemas.py` (add backlog schemas)
- Modify: `src/board/repository.py` (add backlog query)
- Modify: `src/board/routes.py` (add endpoint)
- Test: `tests/board/test_routes.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/board/test_routes.py`:

```python
async def test_backlog_returns_tree(client: AsyncClient):
    project = (await client.post("/api/v1/projects", json={"name": "backlog-test"})).json()
    epic = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics",
            json={"title": "Auth"},
        )
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "OAuth"},
        )
    ).json()
    await client.post(
        f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
        json={"title": "Callback handler"},
    )
    await client.post(
        f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
        json={"title": "Token refresh"},
    )

    resp = await client.get(f"/api/v1/projects/{project['id']}/backlog")
    assert resp.status_code == 200
    data = resp.json()

    assert len(data) == 1
    assert data[0]["epic"]["title"] == "Auth"
    assert data[0]["epic"]["color"].startswith("#")
    assert data[0]["task_counts"]["total"] == 2
    assert data[0]["task_counts"]["done"] == 0

    features = data[0]["features"]
    assert len(features) == 1
    assert features[0]["feature"]["title"] == "OAuth"
    assert features[0]["task_counts"]["total"] == 2
    assert len(features[0]["tasks"]) == 2
    assert features[0]["tasks"][0]["title"] == "Callback handler"


async def test_backlog_counts_done_tasks(client: AsyncClient):
    project = (await client.post("/api/v1/projects", json={"name": "backlog-done"})).json()
    epic = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics",
            json={"title": "Epic"},
        )
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
            json={"title": "Task 1"},
        )
    ).json()
    await client.post(
        f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
        json={"title": "Task 2"},
    )

    # Mark one task as done
    await client.patch(f"/api/v1/tasks/{task['id']}", json={"status": "done"})

    resp = await client.get(f"/api/v1/projects/{project['id']}/backlog")
    data = resp.json()
    assert data[0]["task_counts"]["total"] == 2
    assert data[0]["task_counts"]["done"] == 1
    assert data[0]["features"][0]["task_counts"]["done"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/board/test_routes.py::test_backlog_returns_tree tests/board/test_routes.py::test_backlog_counts_done_tasks -v`
Expected: FAIL — 404 (endpoint doesn't exist)

- [ ] **Step 3: Add backlog schemas**

Add to `src/board/schemas.py`:

```python
# --- Backlog tree view ---


class BacklogTask(BaseModel):
    id: UUID
    title: str
    status: str
    priority: str


class TaskCounts(BaseModel):
    total: int
    done: int


class BacklogFeature(BaseModel):
    feature: FeatureResponse
    tasks: list[BacklogTask]
    task_counts: TaskCounts


class BacklogEpic(BaseModel):
    epic: EpicResponse
    features: list[BacklogFeature]
    task_counts: TaskCounts
```

- [ ] **Step 4: Add backlog query to repository**

Add to `src/board/repository.py`:

```python
    async def get_backlog_tree(self, project_id: UUID) -> list[Epic]:
        """Get all epics with features and tasks eager-loaded for the backlog tree."""
        result = await self._session.execute(
            select(Epic)
            .where(Epic.project_id == project_id)
            .options(
                joinedload(Epic.features).joinedload(Feature.tasks)
            )
            .order_by(Epic.position)
        )
        return list(result.unique().scalars().all())
```

- [ ] **Step 5: Add backlog route**

Add to `src/board/routes.py`:

```python
from src.board.schemas import (
    BacklogEpic,
    BacklogFeature,
    BacklogTask,
    BoardColumn,
    BoardResponse,
    EpicCreate,
    EpicResponse,
    FeatureCreate,
    FeatureResponse,
    ImportPlan,
    ProjectCreate,
    ProjectResponse,
    ProjectWithKey,
    TaskCard,
    TaskCounts,
    TaskCreate,
    TaskResponse,
    TaskUpdate,
)


@router.get("/projects/{project_id}/backlog", response_model=list[BacklogEpic])
async def get_backlog(project_id: UUID, service: ServiceDep) -> list[BacklogEpic]:
    project = await service._repo.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    epics = await service._repo.get_backlog_tree(project_id)
    result = []

    for epic in epics:
        epic_total = 0
        epic_done = 0
        features = []

        for feature in sorted(epic.features, key=lambda f: f.position):
            tasks = sorted(feature.tasks, key=lambda t: t.position)
            feat_total = len(tasks)
            feat_done = sum(1 for t in tasks if t.status == "done")
            epic_total += feat_total
            epic_done += feat_done

            features.append(
                BacklogFeature(
                    feature=FeatureResponse.model_validate(feature),
                    tasks=[
                        BacklogTask(
                            id=t.id,
                            title=t.title,
                            status=t.status,
                            priority=t.priority,
                        )
                        for t in tasks
                    ],
                    task_counts=TaskCounts(total=feat_total, done=feat_done),
                )
            )

        result.append(
            BacklogEpic(
                epic=EpicResponse.model_validate(epic),
                features=features,
                task_counts=TaskCounts(total=epic_total, done=epic_done),
            )
        )

    return result
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/board/test_routes.py -v`
Expected: All pass

- [ ] **Step 7: Run quality gate**

Run: `make quality`
Expected: PASSED

- [ ] **Step 8: Commit**

```bash
git add src/board/schemas.py src/board/repository.py src/board/routes.py tests/board/test_routes.py
git commit -m "feat(board): add /backlog endpoint returning epic > feature > task tree"
```

---

### Task 4: Add document endpoints for epics and features

**Files:**
- Modify: `src/document/routes.py`
- Test: `tests/document/test_routes.py`

- [ ] **Step 1: Write the failing test**

Check the existing test file first, then add:

```python
async def test_list_documents_by_epic(client: AsyncClient):
    # Create a project, epic, and attach a document to the epic
    project = (await client.post("/api/v1/projects", json={"name": "doc-epic"})).json()
    epic = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics",
            json={"title": "Epic"},
        )
    ).json()

    await client.post(
        "/api/v1/documents",
        json={
            "title": "Epic Spec",
            "content": "# Spec content",
            "doc_type": "spec",
            "source_path": "/tmp/spec.md",
            "attached_to_type": "epic",
            "attached_to_id": epic["id"],
        },
    )

    resp = await client.get(
        "/api/v1/documents",
        params={"attached_to_type": "epic", "attached_to_id": epic["id"]},
    )
    assert resp.status_code == 200
    docs = resp.json()
    assert len(docs) == 1
    assert docs[0]["title"] == "Epic Spec"
```

- [ ] **Step 2: Run test**

Run: `uv run pytest tests/document/ -v -k test_list_documents_by_epic`

This test should already pass since the document API already supports `attached_to_type` and `attached_to_id` query params. If it passes, the backend already supports epic/feature document queries — no changes needed. If it fails, investigate and fix.

- [ ] **Step 3: Commit test**

```bash
git add tests/document/
git commit -m "test(document): verify document listing works for epics and features"
```

---

### Task 5: Update frontend API client and types

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/types.ts`

- [ ] **Step 1: Regenerate types from updated backend**

Run:
```bash
uv run python -c "
import yaml
from src.gateway.app import create_app
app = create_app()
schema = app.openapi()
with open('docs/contracts/baseline.openapi.yaml', 'w') as f:
    yaml.dump(schema, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
"
./scripts/generate-contract-types.sh docs/contracts/baseline.openapi.yaml
```

- [ ] **Step 2: Update types.ts re-exports**

Read the generated file and add new type re-exports to `frontend/src/api/types.ts`:

```typescript
// Backlog tree types
export type BacklogEpic = components['schemas']['BacklogEpic']
export type BacklogFeature = components['schemas']['BacklogFeature']
export type BacklogTask = components['schemas']['BacklogTask']
export type TaskCounts = components['schemas']['TaskCounts']
```

- [ ] **Step 3: Add API methods to client**

Add to `frontend/src/api/client.ts`:

```typescript
  // Backlog tree
  getBacklog: (projectId: string) => fetchJSON<BacklogEpic[]>(`/projects/${projectId}/backlog`),

  // Documents for epics/features
  getEpicDocuments: (epicId: string) =>
    fetchJSON<DocumentSummary[]>(`/documents?attached_to_type=epic&attached_to_id=${epicId}`),
  getFeatureDocuments: (featureId: string) =>
    fetchJSON<DocumentSummary[]>(`/documents?attached_to_type=feature&attached_to_id=${featureId}`),
```

Update the import at the top of `client.ts` to include the new types.

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add docs/contracts/baseline.openapi.yaml frontend/src/api/generated-types.ts frontend/src/api/types.ts frontend/src/api/client.ts
git commit -m "feat(frontend): add backlog API types and client methods"
```

---

### Task 6: Create BreadcrumbPills component

**Files:**
- Create: `frontend/src/components/BreadcrumbPills.tsx`
- Create: `frontend/src/components/BreadcrumbPills.css`
- Create: `frontend/src/components/BreadcrumbPills.test.tsx`

- [ ] **Step 1: Write the failing test**

```typescript
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { BreadcrumbPills } from './BreadcrumbPills'

describe('BreadcrumbPills', () => {
  it('renders epic and feature pills', () => {
    render(
      <BreadcrumbPills epicTitle="Auth System" featureTitle="OAuth" epicColor="#7c3aed" />
    )
    expect(screen.getByText('Auth System')).toBeInTheDocument()
    expect(screen.getByText('OAuth')).toBeInTheDocument()
  })

  it('renders only epic pill when no feature title', () => {
    render(
      <BreadcrumbPills epicTitle="Auth System" featureTitle="" epicColor="#7c3aed" />
    )
    expect(screen.getByText('Auth System')).toBeInTheDocument()
    expect(screen.queryByText('OAuth')).not.toBeInTheDocument()
  })

  it('applies epic color as background', () => {
    render(
      <BreadcrumbPills epicTitle="Auth" featureTitle="OAuth" epicColor="#7c3aed" />
    )
    const epicPill = screen.getByText('Auth')
    expect(epicPill).toHaveStyle({ '--pill-color': '#7c3aed' })
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/BreadcrumbPills.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 3: Write the component**

`frontend/src/components/BreadcrumbPills.tsx`:

```typescript
import './BreadcrumbPills.css'

interface BreadcrumbPillsProps {
  epicTitle: string
  featureTitle: string
  epicColor: string
  onEpicClick?: () => void
  onFeatureClick?: () => void
}

export function BreadcrumbPills({
  epicTitle,
  featureTitle,
  epicColor,
  onEpicClick,
  onFeatureClick,
}: BreadcrumbPillsProps) {
  return (
    <div className="breadcrumb-pills">
      <span
        className="pill pill-epic"
        style={{ '--pill-color': epicColor } as React.CSSProperties}
        onClick={onEpicClick}
        role={onEpicClick ? 'button' : undefined}
      >
        {epicTitle}
      </span>
      {featureTitle && (
        <span
          className="pill pill-feature"
          style={{ '--pill-color': epicColor } as React.CSSProperties}
          onClick={onFeatureClick}
          role={onFeatureClick ? 'button' : undefined}
        >
          {featureTitle}
        </span>
      )}
    </div>
  )
}
```

`frontend/src/components/BreadcrumbPills.css`:

```css
.breadcrumb-pills {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.pill {
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 10px;
  line-height: 16px;
  white-space: nowrap;
}

.pill-epic {
  background: color-mix(in srgb, var(--pill-color) 20%, transparent);
  color: var(--pill-color);
}

.pill-feature {
  background: color-mix(in srgb, var(--pill-color) 10%, transparent);
  color: color-mix(in srgb, var(--pill-color) 70%, white);
}

.pill[role="button"] {
  cursor: pointer;
}

.pill[role="button"]:hover {
  filter: brightness(1.2);
}
```

- [ ] **Step 4: Run tests**

Run: `cd frontend && npx vitest run src/components/BreadcrumbPills.test.tsx`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/BreadcrumbPills.tsx frontend/src/components/BreadcrumbPills.css frontend/src/components/BreadcrumbPills.test.tsx
git commit -m "feat(frontend): add BreadcrumbPills component with epic color support"
```

---

### Task 7: Integrate breadcrumb pills into TaskCard

**Files:**
- Modify: `frontend/src/components/TaskCard.tsx`
- Modify: `frontend/src/components/TaskCard.css`
- Modify: `frontend/src/components/TaskCard.test.tsx`

- [ ] **Step 1: Write the failing test**

Update `frontend/src/components/TaskCard.test.tsx` to test for pills instead of text breadcrumb. Add a test:

```typescript
import { BreadcrumbPills } from './BreadcrumbPills'

it('renders breadcrumb pills with epic color', () => {
  const task = {
    ...mockTask,
    epic_title: 'Auth System',
    feature_title: 'OAuth',
    epic_color: '#7c3aed',
  }
  render(<TaskCard task={task} onClick={vi.fn()} />)
  // Pills should render the epic and feature names
  expect(screen.getByText('Auth System')).toBeInTheDocument()
  expect(screen.getByText('OAuth')).toBeInTheDocument()
  // Old text breadcrumb should not exist
  expect(screen.queryByText('Auth System / OAuth')).not.toBeInTheDocument()
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/TaskCard.test.tsx`
Expected: FAIL — still rendering text breadcrumb

- [ ] **Step 3: Update TaskCard to use BreadcrumbPills**

Replace the breadcrumb div in `TaskCard.tsx`:

```typescript
import type { TaskCard as TaskCardType } from '../api/types'
import { BreadcrumbPills } from './BreadcrumbPills'
import './TaskCard.css'

interface TaskCardProps {
  task: TaskCardType
  onClick: () => void
}

export function TaskCard({ task, onClick }: TaskCardProps) {
  return (
    <div
      className={`task-card ${task.status === 'blocked' ? 'task-card-blocked' : ''}`}
      onClick={onClick}
      role="button"
      tabIndex={0}
    >
      <BreadcrumbPills
        epicTitle={task.epic_title}
        featureTitle={task.feature_title}
        epicColor={task.epic_color}
      />
      <div className="task-title">{task.title}</div>
      <div className="task-meta">
        {task.status === 'blocked' && (
          <span className="task-badge task-badge-blocked">blocked</span>
        )}
        {task.priority === 'expedite' && (
          <span className="task-priority">expedite</span>
        )}
        {task.worktree_id && (
          <span className="task-worktree">agent assigned</span>
        )}
      </div>
    </div>
  )
}
```

Add blocked styles to `TaskCard.css`:

```css
.task-card-blocked {
  border-left: 3px solid var(--danger);
}

.task-badge-blocked {
  background: var(--danger);
  color: white;
  padding: 0 6px;
  border-radius: 8px;
  font-size: 10px;
}
```

- [ ] **Step 4: Update mock data in existing TaskCard tests**

Add `epic_color: '#7c3aed'` to all mock task objects in `TaskCard.test.tsx` to match the updated type.

- [ ] **Step 5: Run tests**

Run: `cd frontend && npx vitest run src/components/TaskCard.test.tsx`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/TaskCard.tsx frontend/src/components/TaskCard.css frontend/src/components/TaskCard.test.tsx
git commit -m "feat(frontend): replace text breadcrumb with BreadcrumbPills, add blocked treatment"
```

---

### Task 8: Create BacklogTree component

**Files:**
- Create: `frontend/src/components/BacklogTree.tsx`
- Create: `frontend/src/components/BacklogTree.css`
- Create: `frontend/src/components/BacklogTree.test.tsx`

- [ ] **Step 1: Write the failing test**

```typescript
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import { BacklogTree } from './BacklogTree'
import type { BacklogEpic } from '../api/types'

const mockBacklog: BacklogEpic[] = [
  {
    epic: {
      id: 'e1',
      project_id: 'p1',
      title: 'Auth System',
      description: '',
      bounded_context: '',
      context_description: '',
      status: 'in_progress',
      position: 0,
      created_at: '',
      color: '#7c3aed',
    },
    features: [
      {
        feature: {
          id: 'f1',
          epic_id: 'e1',
          title: 'OAuth',
          description: '',
          status: 'planned',
          position: 0,
          created_at: '',
        },
        tasks: [
          { id: 't1', title: 'Callback handler', status: 'backlog', priority: 'normal' },
          { id: 't2', title: 'Token refresh', status: 'backlog', priority: 'expedite' },
        ],
        task_counts: { total: 2, done: 0 },
      },
    ],
    task_counts: { total: 2, done: 0 },
  },
]

describe('BacklogTree', () => {
  it('renders epic headers', () => {
    render(<BacklogTree backlog={mockBacklog} onItemClick={vi.fn()} />)
    expect(screen.getByText('Auth System')).toBeInTheDocument()
  })

  it('shows task count on epic header', () => {
    render(<BacklogTree backlog={mockBacklog} onItemClick={vi.fn()} />)
    expect(screen.getByText('0/2')).toBeInTheDocument()
  })

  it('expands epic to show features on click', async () => {
    const user = userEvent.setup()
    render(<BacklogTree backlog={mockBacklog} onItemClick={vi.fn()} />)

    // Features should be visible (epics expanded by default)
    expect(screen.getByText('OAuth')).toBeInTheDocument()
  })

  it('expands feature to show tasks', () => {
    render(<BacklogTree backlog={mockBacklog} onItemClick={vi.fn()} />)
    expect(screen.getByText('Callback handler')).toBeInTheDocument()
    expect(screen.getByText('Token refresh')).toBeInTheDocument()
  })

  it('calls onItemClick with epic when epic is clicked', async () => {
    const user = userEvent.setup()
    const onClick = vi.fn()
    render(<BacklogTree backlog={mockBacklog} onItemClick={onClick} />)

    await user.click(screen.getByText('Auth System'))
    expect(onClick).toHaveBeenCalledWith('epic', 'e1')
  })

  it('calls onItemClick with task when task is clicked', async () => {
    const user = userEvent.setup()
    const onClick = vi.fn()
    render(<BacklogTree backlog={mockBacklog} onItemClick={onClick} />)

    await user.click(screen.getByText('Callback handler'))
    expect(onClick).toHaveBeenCalledWith('task', 't1')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/BacklogTree.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 3: Write the component**

`frontend/src/components/BacklogTree.tsx`:

```typescript
import { useState } from 'react'
import type { BacklogEpic } from '../api/types'
import './BacklogTree.css'

interface BacklogTreeProps {
  backlog: BacklogEpic[]
  onItemClick: (type: 'epic' | 'feature' | 'task', id: string) => void
}

export function BacklogTree({ backlog, onItemClick }: BacklogTreeProps) {
  const [expandedEpics, setExpandedEpics] = useState<Set<string>>(
    new Set(backlog.map(e => e.epic.id))
  )
  const [expandedFeatures, setExpandedFeatures] = useState<Set<string>>(
    new Set(backlog.flatMap(e => e.features.map(f => f.feature.id)))
  )

  const toggleEpic = (id: string) => {
    setExpandedEpics(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleFeature = (id: string) => {
    setExpandedFeatures(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <div className="backlog-tree">
      {backlog.map(({ epic, features, task_counts }) => (
        <div key={epic.id} className="backlog-epic">
          <div
            className="backlog-epic-header"
            style={{ borderLeftColor: epic.color }}
            onClick={() => onItemClick('epic', epic.id)}
          >
            <span
              className="backlog-toggle"
              onClick={e => { e.stopPropagation(); toggleEpic(epic.id) }}
            >
              {expandedEpics.has(epic.id) ? '\u25BC' : '\u25B6'}
            </span>
            <span className="backlog-epic-title" style={{ color: epic.color }}>
              {epic.title}
            </span>
            <span className="backlog-count">
              {task_counts.done}/{task_counts.total}
            </span>
          </div>

          {expandedEpics.has(epic.id) && features.map(({ feature, tasks, task_counts: fc }) => (
            <div key={feature.id} className="backlog-feature">
              <div
                className="backlog-feature-header"
                onClick={() => onItemClick('feature', feature.id)}
              >
                <span
                  className="backlog-toggle"
                  onClick={e => { e.stopPropagation(); toggleFeature(feature.id) }}
                >
                  {expandedFeatures.has(feature.id) ? '\u25BC' : '\u25B6'}
                </span>
                <span className="backlog-feature-title">{feature.title}</span>
                <span className="backlog-count">{fc.done}/{fc.total}</span>
              </div>

              {expandedFeatures.has(feature.id) && (
                <div className="backlog-tasks">
                  {tasks.map(task => (
                    <div
                      key={task.id}
                      className="backlog-task"
                      onClick={() => onItemClick('task', task.id)}
                    >
                      {task.title}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}
```

`frontend/src/components/BacklogTree.css`:

```css
.backlog-tree {
  overflow-y: auto;
}

.backlog-epic {
  margin-bottom: 16px;
}

.backlog-epic-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  background: color-mix(in srgb, var(--surface) 80%, transparent);
  border-left: 3px solid;
  border-radius: 0 6px 6px 0;
  cursor: pointer;
  margin-bottom: 4px;
}

.backlog-epic-title {
  font-size: 13px;
  font-weight: 600;
}

.backlog-toggle {
  font-size: 10px;
  color: var(--text-muted);
  cursor: pointer;
  user-select: none;
  width: 12px;
}

.backlog-count {
  color: var(--text-muted);
  font-size: 11px;
  margin-left: auto;
}

.backlog-feature {
  margin-left: 12px;
  margin-bottom: 4px;
}

.backlog-feature-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  cursor: pointer;
}

.backlog-feature-title {
  font-size: 12px;
  color: var(--text);
}

.backlog-tasks {
  margin-left: 20px;
}

.backlog-task {
  padding: 8px 10px;
  background: var(--surface);
  border-radius: 6px;
  margin-bottom: 4px;
  border: 1px solid var(--border);
  font-size: 12px;
  color: var(--text);
  cursor: pointer;
}

.backlog-task:hover {
  border-color: var(--text-muted);
}
```

- [ ] **Step 4: Run tests**

Run: `cd frontend && npx vitest run src/components/BacklogTree.test.tsx`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/BacklogTree.tsx frontend/src/components/BacklogTree.css frontend/src/components/BacklogTree.test.tsx
git commit -m "feat(frontend): add BacklogTree component with collapsible epic/feature/task tree"
```

---

### Task 9: Create DetailPanel component

**Files:**
- Create: `frontend/src/components/DetailPanel.tsx`
- Create: `frontend/src/components/DetailPanel.css`
- Create: `frontend/src/components/DetailPanel.test.tsx`

- [ ] **Step 1: Write the failing test**

```typescript
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import { DetailPanel } from './DetailPanel'

describe('DetailPanel', () => {
  it('renders epic detail', () => {
    render(
      <DetailPanel
        type="epic"
        data={{
          title: 'Auth System',
          description: 'Authentication epic',
          color: '#7c3aed',
          bounded_context: 'Agent',
          task_counts: { total: 8, done: 2 },
          features: [
            { title: 'OAuth', task_counts: { total: 3, done: 1 } },
            { title: 'Session', task_counts: { total: 5, done: 1 } },
          ],
        }}
        onClose={vi.fn()}
        onNavigate={vi.fn()}
      />
    )
    expect(screen.getByText('Auth System')).toBeInTheDocument()
    expect(screen.getByText('Authentication epic')).toBeInTheDocument()
    expect(screen.getByText('OAuth')).toBeInTheDocument()
    expect(screen.getByText('Session')).toBeInTheDocument()
  })

  it('renders feature detail with parent epic pill', () => {
    render(
      <DetailPanel
        type="feature"
        data={{
          title: 'OAuth Provider',
          description: 'OAuth implementation',
          epic: { title: 'Auth System', id: 'e1', color: '#7c3aed' },
          task_counts: { total: 3, done: 1 },
          tasks: [
            { id: 't1', title: 'Callback', status: 'done' },
            { id: 't2', title: 'Token refresh', status: 'backlog' },
          ],
        }}
        onClose={vi.fn()}
        onNavigate={vi.fn()}
      />
    )
    expect(screen.getByText('OAuth Provider')).toBeInTheDocument()
    expect(screen.getByText('Auth System')).toBeInTheDocument()
    expect(screen.getByText('Callback')).toBeInTheDocument()
  })

  it('renders task detail with breadcrumb pills', () => {
    render(
      <DetailPanel
        type="task"
        data={{
          title: 'Add callback handler',
          description: 'Implement the OAuth callback',
          status: 'in_progress',
          priority: 'normal',
          epic: { title: 'Auth System', id: 'e1', color: '#7c3aed' },
          feature: { title: 'OAuth', id: 'f1' },
          worktree_id: null,
        }}
        onClose={vi.fn()}
        onNavigate={vi.fn()}
      />
    )
    expect(screen.getByText('Add callback handler')).toBeInTheDocument()
    expect(screen.getByText('Auth System')).toBeInTheDocument()
    expect(screen.getByText('OAuth')).toBeInTheDocument()
  })

  it('calls onClose when overlay is clicked', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    render(
      <DetailPanel
        type="epic"
        data={{ title: 'Test', description: '', color: '#000', bounded_context: '', task_counts: { total: 0, done: 0 }, features: [] }}
        onClose={onClose}
        onNavigate={vi.fn()}
      />
    )
    await user.click(screen.getByTestId('detail-overlay'))
    expect(onClose).toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/DetailPanel.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 3: Write the component**

`frontend/src/components/DetailPanel.tsx`:

```typescript
import { BreadcrumbPills } from './BreadcrumbPills'
import './DetailPanel.css'

interface EpicData {
  title: string
  description: string
  color: string
  bounded_context: string
  task_counts: { total: number; done: number }
  features: Array<{ title: string; task_counts: { total: number; done: number } }>
}

interface FeatureData {
  title: string
  description: string
  epic: { title: string; id: string; color: string }
  task_counts: { total: number; done: number }
  tasks: Array<{ id: string; title: string; status: string }>
}

interface TaskData {
  title: string
  description: string
  status: string
  priority: string
  epic: { title: string; id: string; color: string }
  feature: { title: string; id: string }
  worktree_id: string | null
}

type DetailPanelProps = {
  onClose: () => void
  onNavigate: (type: 'epic' | 'feature' | 'task', id: string) => void
} & (
  | { type: 'epic'; data: EpicData }
  | { type: 'feature'; data: FeatureData }
  | { type: 'task'; data: TaskData }
)

export function DetailPanel({ type, data, onClose, onNavigate }: DetailPanelProps) {
  return (
    <div className="detail-overlay" data-testid="detail-overlay" onClick={onClose}>
      <div className="detail-panel" onClick={e => e.stopPropagation()}>
        <button className="detail-close" onClick={onClose}>x</button>

        {type === 'epic' && <EpicDetail data={data as EpicData} />}
        {type === 'feature' && <FeatureDetail data={data as FeatureData} onNavigate={onNavigate} />}
        {type === 'task' && <TaskDetail data={data as TaskData} onNavigate={onNavigate} />}
      </div>
    </div>
  )
}

function ProgressBar({ done, total }: { done: number; total: number }) {
  const pct = total === 0 ? 0 : Math.round((done / total) * 100)
  return (
    <div className="detail-progress">
      <div className="detail-progress-bar">
        <div className="detail-progress-fill" style={{ width: `${pct}%` }} />
      </div>
      <span className="detail-progress-text">{done}/{total} tasks ({pct}%)</span>
    </div>
  )
}

function EpicDetail({ data }: { data: EpicData }) {
  return (
    <>
      <div className="detail-header" style={{ borderLeftColor: data.color }}>
        <h2 className="detail-title">{data.title}</h2>
        {data.bounded_context && (
          <span className="detail-badge">{data.bounded_context}</span>
        )}
      </div>
      <ProgressBar done={data.task_counts.done} total={data.task_counts.total} />
      {data.description && <p className="detail-description">{data.description}</p>}
      {data.features.length > 0 && (
        <div className="detail-section">
          <h3>Features</h3>
          {data.features.map((f, i) => (
            <div key={i} className="detail-list-item">
              <span>{f.title}</span>
              <span className="detail-count">{f.task_counts.done}/{f.task_counts.total}</span>
            </div>
          ))}
        </div>
      )}
    </>
  )
}

function FeatureDetail({ data, onNavigate }: { data: FeatureData; onNavigate: (type: 'epic' | 'feature' | 'task', id: string) => void }) {
  return (
    <>
      <div className="detail-header">
        <span
          className="detail-parent-pill"
          style={{ background: `color-mix(in srgb, ${data.epic.color} 20%, transparent)`, color: data.epic.color }}
          onClick={() => onNavigate('epic', data.epic.id)}
        >
          {data.epic.title}
        </span>
        <h2 className="detail-title">{data.title}</h2>
      </div>
      <ProgressBar done={data.task_counts.done} total={data.task_counts.total} />
      {data.description && <p className="detail-description">{data.description}</p>}
      {data.tasks.length > 0 && (
        <div className="detail-section">
          <h3>Tasks</h3>
          {data.tasks.map(t => (
            <div key={t.id} className="detail-list-item" onClick={() => onNavigate('task', t.id)}>
              <span>{t.title}</span>
              <span className={`detail-status status-${t.status}`}>{t.status}</span>
            </div>
          ))}
        </div>
      )}
    </>
  )
}

function TaskDetail({ data, onNavigate }: { data: TaskData; onNavigate: (type: 'epic' | 'feature' | 'task', id: string) => void }) {
  return (
    <>
      <div className="detail-header">
        <BreadcrumbPills
          epicTitle={data.epic.title}
          featureTitle={data.feature.title}
          epicColor={data.epic.color}
          onEpicClick={() => onNavigate('epic', data.epic.id)}
          onFeatureClick={() => onNavigate('feature', data.feature.id)}
        />
        <h2 className="detail-title">{data.title}</h2>
        <div className="detail-meta">
          <span className={`detail-status status-${data.status}`}>{data.status}</span>
          {data.priority === 'expedite' && <span className="detail-badge expedite">expedite</span>}
          {data.worktree_id && <span className="detail-agent">agent assigned</span>}
        </div>
      </div>
      {data.description && <p className="detail-description">{data.description}</p>}
    </>
  )
}
```

`frontend/src/components/DetailPanel.css`:

```css
.detail-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 100;
  display: flex;
  justify-content: flex-end;
}

.detail-panel {
  width: 400px;
  max-width: 90vw;
  background: var(--bg);
  border-left: 1px solid var(--border);
  padding: 24px;
  overflow-y: auto;
  position: relative;
}

.detail-close {
  position: absolute;
  top: 12px;
  right: 12px;
  background: none;
  border: none;
  color: var(--text-muted);
  font-size: 18px;
  cursor: pointer;
  padding: 4px 8px;
}

.detail-header {
  margin-bottom: 16px;
  border-left: 3px solid transparent;
  padding-left: 0;
}

.detail-header[style*="borderLeftColor"] {
  padding-left: 12px;
}

.detail-title {
  font-size: 18px;
  font-weight: 600;
  margin: 8px 0;
}

.detail-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 11px;
  background: var(--surface);
  color: var(--text-muted);
}

.detail-badge.expedite {
  background: var(--warning);
  color: var(--bg);
}

.detail-progress {
  margin-bottom: 16px;
}

.detail-progress-bar {
  height: 6px;
  background: var(--surface);
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 4px;
}

.detail-progress-fill {
  height: 100%;
  background: var(--active);
  border-radius: 3px;
  transition: width 0.3s ease;
}

.detail-progress-text {
  font-size: 12px;
  color: var(--text-muted);
}

.detail-description {
  font-size: 14px;
  color: var(--text);
  line-height: 1.6;
  margin-bottom: 16px;
}

.detail-section {
  margin-top: 20px;
}

.detail-section h3 {
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted);
  margin-bottom: 8px;
}

.detail-list-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
}

.detail-list-item:hover {
  background: var(--surface);
}

.detail-count {
  color: var(--text-muted);
  font-size: 12px;
}

.detail-status {
  font-size: 11px;
  padding: 1px 8px;
  border-radius: 8px;
}

.status-backlog { background: var(--surface); color: var(--text-muted); }
.status-assigned { background: #3b82f620; color: #60a5fa; }
.status-in_progress { background: #f59e0b20; color: #fbbf24; }
.status-review { background: #8b5cf620; color: #a78bfa; }
.status-done { background: #10b98120; color: #6ee7b7; }
.status-blocked { background: #ef444420; color: #f87171; }

.detail-meta {
  display: flex;
  gap: 8px;
  align-items: center;
}

.detail-agent {
  font-size: 11px;
  color: var(--active);
}

.detail-parent-pill {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 11px;
  cursor: pointer;
}

.detail-parent-pill:hover {
  filter: brightness(1.2);
}
```

- [ ] **Step 4: Run tests**

Run: `cd frontend && npx vitest run src/components/DetailPanel.test.tsx`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/DetailPanel.tsx frontend/src/components/DetailPanel.css frontend/src/components/DetailPanel.test.tsx
git commit -m "feat(frontend): add multi-level DetailPanel for epic/feature/task views"
```

---

### Task 10: Wire everything together in Board and App

**Files:**
- Modify: `frontend/src/components/Board.tsx`
- Modify: `frontend/src/components/Board.css`
- Modify: `frontend/src/hooks/useBoard.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Board.test.tsx`
- Modify: `frontend/src/App.integration.test.tsx`

- [ ] **Step 1: Update useBoard to fetch backlog**

In `frontend/src/hooks/useBoard.ts`, add the backlog fetch:

```typescript
import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { BacklogEpic, BoardResponse, SSEEvent, Worktree } from '../api/types'
import { useSSE } from './useSSE'

export function useBoard(projectId: string | null) {
  const [board, setBoard] = useState<BoardResponse | null>(null)
  const [backlog, setBacklog] = useState<BacklogEpic[]>([])
  const [worktrees, setWorktrees] = useState<Worktree[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchBoard = useCallback(async () => {
    if (!projectId) return
    setLoading(true)
    try {
      const [boardData, backlogData, wtData] = await Promise.all([
        api.getBoard(projectId),
        api.getBacklog(projectId),
        api.getWorktrees(projectId),
      ])
      setBoard(boardData)
      setBacklog(backlogData)
      setWorktrees(wtData)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load board')
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    fetchBoard()
  }, [fetchBoard])

  const handleSSE = useCallback((_event: SSEEvent) => {
    fetchBoard()
  }, [fetchBoard])

  useSSE(projectId, handleSSE)

  return { board, backlog, worktrees, loading, error, refetch: fetchBoard }
}
```

- [ ] **Step 2: Update Board component to include backlog column**

Replace `frontend/src/components/Board.tsx`:

```typescript
import type { BacklogEpic, BoardResponse } from '../api/types'
import { BacklogTree } from './BacklogTree'
import { BoardHeader } from './BoardHeader'
import { Column } from './Column'
import './Board.css'

interface BoardProps {
  board: BoardResponse
  backlog: BacklogEpic[]
  onTaskClick: (taskId: string) => void
  onItemClick: (type: 'epic' | 'feature' | 'task', id: string) => void
}

export function Board({ board, backlog, onTaskClick, onItemClick }: BoardProps) {
  // Filter out backlog from flow columns — backlog is shown as tree
  const flowColumns = board.columns.filter(col => col.status !== 'backlog')

  return (
    <div className="board">
      <BoardHeader board={board} />
      <div className="board-columns">
        <div className="board-backlog">
          <div className="column-header">
            <span className="column-dot col-backlog" />
            <span className="column-title">Backlog</span>
            <span className="column-count">
              {board.columns.find(c => c.status === 'backlog')?.tasks.length ?? 0}
            </span>
          </div>
          <BacklogTree backlog={backlog} onItemClick={onItemClick} />
        </div>
        {flowColumns.map(col => (
          <Column key={col.status} column={col} onTaskClick={onTaskClick} />
        ))}
      </div>
    </div>
  )
}
```

Add to `Board.css`:

```css
.board-backlog {
  width: 280px;
  min-width: 280px;
  border-right: 1px solid var(--border);
  padding: 12px;
  overflow-y: auto;
}
```

- [ ] **Step 3: Update App.tsx to wire detail panel and backlog**

Replace `frontend/src/App.tsx`:

```typescript
import { useCallback, useState } from 'react'
import { api } from './api/client'
import { Board } from './components/Board'
import { DetailPanel } from './components/DetailPanel'
import { Layout } from './components/Layout'
import { useBoard } from './hooks/useBoard'
import { useProjects } from './hooks/useProjects'

type DetailState =
  | { type: 'epic'; id: string; data: any }
  | { type: 'feature'; id: string; data: any }
  | { type: 'task'; id: string; data: any }
  | null

export default function App() {
  const { projects, loading: projectsLoading } = useProjects()
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null)
  const { board, backlog, worktrees, loading: boardLoading } = useBoard(selectedProjectId)
  const [detail, setDetail] = useState<DetailState>(null)

  const openDetail = useCallback(async (type: 'epic' | 'feature' | 'task', id: string) => {
    if (type === 'epic') {
      const epicEntry = backlog.find(e => e.epic.id === id)
      if (epicEntry) {
        setDetail({
          type: 'epic',
          id,
          data: {
            title: epicEntry.epic.title,
            description: epicEntry.epic.description,
            color: epicEntry.epic.color,
            bounded_context: epicEntry.epic.bounded_context,
            task_counts: epicEntry.task_counts,
            features: epicEntry.features.map(f => ({
              title: f.feature.title,
              task_counts: f.task_counts,
            })),
          },
        })
      }
    } else if (type === 'feature') {
      for (const epicEntry of backlog) {
        const feat = epicEntry.features.find(f => f.feature.id === id)
        if (feat) {
          setDetail({
            type: 'feature',
            id,
            data: {
              title: feat.feature.title,
              description: feat.feature.description,
              epic: { title: epicEntry.epic.title, id: epicEntry.epic.id, color: epicEntry.epic.color },
              task_counts: feat.task_counts,
              tasks: feat.tasks.map(t => ({ id: t.id, title: t.title, status: t.status })),
            },
          })
          break
        }
      }
    } else {
      // Task — find in board columns or backlog
      if (!board) return
      for (const col of board.columns) {
        const task = col.tasks.find(t => t.id === id)
        if (task) {
          // Find parent epic/feature from backlog
          let epicInfo = { title: task.epic_title, id: '', color: task.epic_color }
          let featureInfo = { title: task.feature_title, id: '' }
          for (const e of backlog) {
            for (const f of e.features) {
              if (f.tasks.some(t => t.id === id)) {
                epicInfo = { title: e.epic.title, id: e.epic.id, color: e.epic.color }
                featureInfo = { title: f.feature.title, id: f.feature.id }
              }
            }
          }
          setDetail({
            type: 'task',
            id,
            data: {
              title: task.title,
              description: task.description,
              status: task.status,
              priority: task.priority,
              epic: epicInfo,
              feature: featureInfo,
              worktree_id: task.worktree_id,
            },
          })
          return
        }
      }
      // Task might be in backlog only
      for (const e of backlog) {
        for (const f of e.features) {
          const t = f.tasks.find(bt => bt.id === id)
          if (t) {
            setDetail({
              type: 'task',
              id,
              data: {
                title: t.title,
                description: '',
                status: t.status,
                priority: t.priority,
                epic: { title: e.epic.title, id: e.epic.id, color: e.epic.color },
                feature: { title: f.feature.title, id: f.feature.id },
                worktree_id: null,
              },
            })
            return
          }
        }
      }
    }
  }, [backlog, board])

  const handleTaskClick = useCallback((taskId: string) => {
    openDetail('task', taskId)
  }, [openDetail])

  return (
    <Layout
      projects={projects}
      selectedProjectId={selectedProjectId}
      onSelectProject={setSelectedProjectId}
      worktrees={worktrees}
    >
      {!selectedProjectId && (
        <div className="board-placeholder">
          {projectsLoading ? 'loading projects...' : 'select a project'}
        </div>
      )}

      {selectedProjectId && boardLoading && (
        <div className="board-placeholder">loading board...</div>
      )}

      {board && !boardLoading && (
        <Board
          board={board}
          backlog={backlog}
          onTaskClick={handleTaskClick}
          onItemClick={openDetail}
        />
      )}

      {detail && (
        <DetailPanel
          type={detail.type}
          data={detail.data}
          onClose={() => setDetail(null)}
          onNavigate={openDetail}
        />
      )}
    </Layout>
  )
}
```

- [ ] **Step 4: Update existing tests**

Update `Board.test.tsx` mock data and props to include `backlog` and `onItemClick`. Update `App.integration.test.tsx` to mock the backlog API response.

The mock for `api.getBacklog` should return an empty array `[]` for tests that don't focus on backlog behavior.

- [ ] **Step 5: Run all frontend tests**

Run: `cd frontend && npx vitest run`
Expected: All pass

- [ ] **Step 6: Run TypeScript check**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/Board.tsx frontend/src/components/Board.css frontend/src/hooks/useBoard.ts frontend/src/App.tsx frontend/src/components/Board.test.tsx frontend/src/App.integration.test.tsx
git commit -m "feat(frontend): wire backlog tree, detail panel, and breadcrumb pills into board"
```

---

### Task 11: Run full quality gate

- [ ] **Step 1: Run backend quality**

Run: `make quality`
Expected: PASSED

- [ ] **Step 2: Run frontend tests**

Run: `cd frontend && npx tsc --noEmit && npx vitest run`
Expected: All pass

- [ ] **Step 3: Run contract check**

Run: `make contract-check`
Expected: "Contract check passed"

- [ ] **Step 4: Verify the board visually**

Run the backend and frontend:
```bash
make run-backend &
cd frontend && npm run dev
```
Open the dashboard, select the cloglog project, and verify:
- Backlog shows the 5 epics as a collapsible tree with colors
- Each epic expands to show features and tasks
- In-flight cards (if any) show breadcrumb pills with epic colors
- Clicking any item opens the detail panel
- Detail panel navigation works (click epic pill → epic detail)
