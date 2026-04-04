# Entity Numbering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add project-scoped sequential numbers (E-1, F-3, T-37) to epics, features, and tasks so they can be referenced by short identifiers.

**Architecture:** Add `number` integer column to all three models, auto-assign on creation via max+1 query, backfill existing rows via Alembic migration. Frontend formats with prefix.

**Tech Stack:** Python/SQLAlchemy/Alembic (backend), React/TypeScript (frontend)

---

### Task 1: Add number column to models + migration with backfill

**Files:**
- Modify: `src/board/models.py:32-103`
- Create: `src/alembic/versions/xxxx_add_entity_numbers.py` (via autogenerate)
- Test: `tests/board/test_routes.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/board/test_routes.py`:

```python
async def test_epic_response_includes_number(client: AsyncClient):
    project = (await client.post("/api/v1/projects", json={"name": "num-test"})).json()
    epic = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics",
            json={"title": "First Epic"},
        )
    ).json()
    assert "number" in epic
    assert epic["number"] == 1


async def test_entity_numbers_auto_increment(client: AsyncClient):
    project = (await client.post("/api/v1/projects", json={"name": "num-incr"})).json()
    e1 = (await client.post(f"/api/v1/projects/{project['id']}/epics", json={"title": "E1"})).json()
    e2 = (await client.post(f"/api/v1/projects/{project['id']}/epics", json={"title": "E2"})).json()
    assert e1["number"] == 1
    assert e2["number"] == 2

    f1 = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{e1['id']}/features",
            json={"title": "F1"},
        )
    ).json()
    f2 = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{e2['id']}/features",
            json={"title": "F2"},
        )
    ).json()
    assert f1["number"] == 1
    assert f2["number"] == 2

    t1 = (
        await client.post(
            f"/api/v1/projects/{project['id']}/features/{f1['id']}/tasks",
            json={"title": "T1"},
        )
    ).json()
    t2 = (
        await client.post(
            f"/api/v1/projects/{project['id']}/features/{f2['id']}/tasks",
            json={"title": "T2"},
        )
    ).json()
    assert t1["number"] == 1
    assert t2["number"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/board/test_routes.py::test_epic_response_includes_number tests/board/test_routes.py::test_entity_numbers_auto_increment -v`
Expected: FAIL — `number` not in response

- [ ] **Step 3: Add number column to all three models**

In `src/board/models.py`, add to Epic class after `color`:

```python
    number: Mapped[int] = mapped_column(default=0)
```

Add to Feature class after `position`:

```python
    number: Mapped[int] = mapped_column(default=0)
```

Add to Task class after `position`:

```python
    number: Mapped[int] = mapped_column(default=0)
```

- [ ] **Step 4: Add number to response schemas**

In `src/board/schemas.py`, add `number: int` to:

- `EpicResponse` (after `color: str`)
- `FeatureResponse` (after `position: int`)
- `TaskResponse` (after `position: int`)
- `BacklogTask` (after `id: UUID`)

- [ ] **Step 5: Add next_number repository methods**

In `src/board/repository.py`, add three methods. First add `coalesce` to the imports:

```python
from sqlalchemy import coalesce, func, select
```

Then add these methods to `BoardRepository`:

```python
    async def next_epic_number(self, project_id: UUID) -> int:
        result = await self._session.execute(
            select(coalesce(func.max(Epic.number), 0))
            .where(Epic.project_id == project_id)
        )
        return result.scalar_one() + 1

    async def next_feature_number(self, project_id: UUID) -> int:
        result = await self._session.execute(
            select(coalesce(func.max(Feature.number), 0))
            .select_from(Feature)
            .join(Epic, Feature.epic_id == Epic.id)
            .where(Epic.project_id == project_id)
        )
        return result.scalar_one() + 1

    async def next_task_number(self, project_id: UUID) -> int:
        result = await self._session.execute(
            select(coalesce(func.max(Task.number), 0))
            .select_from(Task)
            .join(Feature, Task.feature_id == Feature.id)
            .join(Epic, Feature.epic_id == Epic.id)
            .where(Epic.project_id == project_id)
        )
        return result.scalar_one() + 1
```

- [ ] **Step 6: Update create_epic to auto-assign number**

Update `create_epic` in `repository.py` to accept and set `number`:

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
        number: int = 0,
    ) -> Epic:
        epic = Epic(
            project_id=project_id,
            title=title,
            description=description,
            bounded_context=bounded_context,
            context_description=context_description,
            position=position,
            color=color,
            number=number,
        )
        self._session.add(epic)
        await self._session.commit()
        await self._session.refresh(epic)
        return epic
```

Update the `create_epic` route in `routes.py` to assign the next number:

```python
    number = await service._repo.next_epic_number(project_id)
    epic = await service._repo.create_epic(
        project_id,
        body.title,
        body.description,
        body.bounded_context,
        body.context_description,
        body.position,
        color=color,
        number=number,
    )
```

- [ ] **Step 7: Update create_feature to auto-assign number**

Update `create_feature` in `repository.py`:

```python
    async def create_feature(
        self, epic_id: UUID, title: str, description: str, position: int, number: int = 0
    ) -> Feature:
        feature = Feature(
            epic_id=epic_id, title=title, description=description, position=position, number=number
        )
        self._session.add(feature)
        await self._session.commit()
        await self._session.refresh(feature)
        return feature
```

Update the `create_feature` route in `routes.py`. You need the project_id to get the next number. The route already has `project_id` as a path param:

```python
    number = await service._repo.next_feature_number(project_id)
    feature = await service._repo.create_feature(
        epic_id, body.title, body.description, body.position, number=number
    )
```

- [ ] **Step 8: Update create_task to auto-assign number**

Update `create_task` in `repository.py`:

```python
    async def create_task(
        self,
        feature_id: UUID,
        title: str,
        description: str,
        priority: str,
        position: int,
        number: int = 0,
    ) -> Task:
        task = Task(
            feature_id=feature_id,
            title=title,
            description=description,
            priority=priority,
            position=position,
            number=number,
        )
        self._session.add(task)
        await self._session.commit()
        await self._session.refresh(task)
        return task
```

Update the `create_task` route in `routes.py`. The route has `project_id` as a path param:

```python
    number = await service._repo.next_task_number(project_id)
    task = await service._repo.create_task(
        feature_id, body.title, body.description, body.priority, body.position, number=number
    )
```

- [ ] **Step 9: Update import_plan to assign numbers**

In `src/board/services.py`, update `import_plan` to get and assign numbers:

```python
    async def import_plan(self, project_id: UUID, plan: ImportPlan) -> dict[str, int]:
        """Bulk import epics/features/tasks from a structured plan."""
        epics_created = 0
        features_created = 0
        tasks_created = 0

        existing_count = await self._repo.count_epics(project_id)
        next_epic_num = await self._repo.next_epic_number(project_id)
        next_feat_num = await self._repo.next_feature_number(project_id)
        next_task_num = await self._repo.next_task_number(project_id)

        for epic_pos, epic_data in enumerate(plan.epics):
            color = EPIC_COLOR_PALETTE[(existing_count + epic_pos) % len(EPIC_COLOR_PALETTE)]
            epic = await self._repo.create_epic(
                project_id=project_id,
                title=epic_data.title,
                description=epic_data.description,
                bounded_context=epic_data.bounded_context,
                context_description="",
                position=epic_pos,
                color=color,
                number=next_epic_num,
            )
            next_epic_num += 1
            epics_created += 1

            for feat_pos, feat_data in enumerate(epic_data.features):
                feature = await self._repo.create_feature(
                    epic_id=epic.id,
                    title=feat_data.title,
                    description=feat_data.description,
                    position=feat_pos,
                    number=next_feat_num,
                )
                next_feat_num += 1
                features_created += 1

                for task_pos, task_data in enumerate(feat_data.tasks):
                    await self._repo.create_task(
                        feature_id=feature.id,
                        title=task_data.title,
                        description=task_data.description,
                        priority=task_data.priority,
                        position=task_pos,
                        number=next_task_num,
                    )
                    next_task_num += 1
                    tasks_created += 1

        return {
            "epics_created": epics_created,
            "features_created": features_created,
            "tasks_created": tasks_created,
        }
```

- [ ] **Step 10: Generate Alembic migration with backfill**

Run: `uv run alembic revision --autogenerate -m "add_entity_numbers"`

Edit the generated migration to include backfill logic:

```python
def upgrade() -> None:
    op.add_column("epics", sa.Column("number", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("features", sa.Column("number", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("tasks", sa.Column("number", sa.Integer(), nullable=False, server_default="0"))

    # Backfill: assign numbers by created_at order within each project
    conn = op.get_bind()

    # Backfill epics
    projects = conn.execute(sa.text("SELECT DISTINCT project_id FROM epics")).fetchall()
    for (project_id,) in projects:
        epics = conn.execute(
            sa.text("SELECT id FROM epics WHERE project_id = :pid ORDER BY created_at"),
            {"pid": project_id},
        ).fetchall()
        for i, (epic_id,) in enumerate(epics, 1):
            conn.execute(
                sa.text("UPDATE epics SET number = :num WHERE id = :id"),
                {"num": i, "id": epic_id},
            )

    # Backfill features (project-scoped via epic join)
    for (project_id,) in projects:
        features = conn.execute(
            sa.text(
                "SELECT f.id FROM features f JOIN epics e ON f.epic_id = e.id "
                "WHERE e.project_id = :pid ORDER BY f.created_at"
            ),
            {"pid": project_id},
        ).fetchall()
        for i, (feat_id,) in enumerate(features, 1):
            conn.execute(
                sa.text("UPDATE features SET number = :num WHERE id = :id"),
                {"num": i, "id": feat_id},
            )

    # Backfill tasks (project-scoped via feature+epic join)
    for (project_id,) in projects:
        tasks = conn.execute(
            sa.text(
                "SELECT t.id FROM tasks t JOIN features f ON t.feature_id = f.id "
                "JOIN epics e ON f.epic_id = e.id "
                "WHERE e.project_id = :pid ORDER BY t.created_at"
            ),
            {"pid": project_id},
        ).fetchall()
        for i, (task_id,) in enumerate(tasks, 1):
            conn.execute(
                sa.text("UPDATE tasks SET number = :num WHERE id = :id"),
                {"num": i, "id": task_id},
            )
```

Run: `uv run alembic upgrade head`

- [ ] **Step 11: Run tests**

Run: `uv run pytest tests/board/test_routes.py -v`
Expected: All pass including the 2 new tests

- [ ] **Step 12: Run quality gate**

Run: `make quality`
Expected: PASSED

- [ ] **Step 13: Commit**

```bash
git add src/board/models.py src/board/schemas.py src/board/repository.py src/board/services.py src/board/routes.py src/alembic/versions/ tests/board/test_routes.py
git commit -m "feat(board): add project-scoped entity numbers to epics, features, tasks"
```

---

### Task 2: Update contract and regenerate frontend types

**Files:**
- Modify: `docs/contracts/baseline.openapi.yaml`
- Modify: `frontend/src/api/generated-types.ts` (regenerated)
- Modify: `frontend/src/api/types.ts`

- [ ] **Step 1: Regenerate contract from updated backend**

```bash
uv run python -c "
import yaml
from src.gateway.app import create_app
app = create_app()
schema = app.openapi()
with open('docs/contracts/baseline.openapi.yaml', 'w') as f:
    yaml.dump(schema, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
"
```

- [ ] **Step 2: Regenerate TypeScript types**

Run: `./scripts/generate-contract-types.sh docs/contracts/baseline.openapi.yaml`

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors (the `number` field is added automatically to all re-exported types)

- [ ] **Step 4: Commit**

```bash
git add docs/contracts/baseline.openapi.yaml frontend/src/api/generated-types.ts
git commit -m "feat: regenerate contract and frontend types with entity numbers"
```

---

### Task 3: Add formatEntityNumber helper and update frontend components

**Files:**
- Create: `frontend/src/utils/format.ts`
- Create: `frontend/src/utils/format.test.ts`
- Modify: `frontend/src/components/BacklogTree.tsx`
- Modify: `frontend/src/components/BreadcrumbPills.tsx`
- Modify: `frontend/src/components/DetailPanel.tsx`
- Modify: various test files for updated props

- [ ] **Step 1: Write failing test for helper**

Create `frontend/src/utils/format.test.ts`:

```typescript
import { describe, it, expect } from 'vitest'
import { formatEntityNumber } from './format'

describe('formatEntityNumber', () => {
  it('formats epic numbers', () => {
    expect(formatEntityNumber('epic', 1)).toBe('E-1')
    expect(formatEntityNumber('epic', 12)).toBe('E-12')
  })

  it('formats feature numbers', () => {
    expect(formatEntityNumber('feature', 3)).toBe('F-3')
  })

  it('formats task numbers', () => {
    expect(formatEntityNumber('task', 37)).toBe('T-37')
  })

  it('returns empty string for number 0', () => {
    expect(formatEntityNumber('task', 0)).toBe('')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/utils/format.test.ts`
Expected: FAIL — module not found

- [ ] **Step 3: Write the helper**

Create `frontend/src/utils/format.ts`:

```typescript
const PREFIXES: Record<string, string> = {
  epic: 'E',
  feature: 'F',
  task: 'T',
}

export function formatEntityNumber(type: string, number: number): string {
  if (number === 0) return ''
  const prefix = PREFIXES[type] ?? '?'
  return `${prefix}-${number}`
}
```

- [ ] **Step 4: Run test**

Run: `cd frontend && npx vitest run src/utils/format.test.ts`
Expected: PASS

- [ ] **Step 5: Update BacklogTree to show numbers**

In `frontend/src/components/BacklogTree.tsx`, import the helper:

```typescript
import { formatEntityNumber } from '../utils/format'
```

Update the epic title rendering (the line with `{epic.title}`):

```typescript
<span
  className="backlog-epic-title"
  style={{ color: epic.color }}
  onClick={() => onItemClick('epic', epic.id)}
>
  {epic.number > 0 && <span className="entity-number">{formatEntityNumber('epic', epic.number)} </span>}
  {epic.title}
</span>
```

Update the feature title rendering:

```typescript
<span
  className="backlog-feature-title"
  onClick={() => onItemClick('feature', feature.id)}
>
  {feature.number > 0 && <span className="entity-number">{formatEntityNumber('feature', feature.number)} </span>}
  {feature.title}
</span>
```

Update the task rendering:

```typescript
<div
  key={task.id}
  className="backlog-task"
  onClick={() => onItemClick('task', task.id)}
>
  {task.number > 0 && <span className="entity-number">{formatEntityNumber('task', task.number)} </span>}
  {task.title}
</div>
```

Add to `BacklogTree.css`:

```css
.entity-number {
  color: var(--text-muted, #666);
  font-size: 0.9em;
}
```

- [ ] **Step 6: Update BreadcrumbPills to show numbers**

Add `epicNumber` and `featureNumber` optional props to `BreadcrumbPills`:

```typescript
interface BreadcrumbPillsProps {
  epicTitle: string
  featureTitle: string
  epicColor: string
  epicNumber?: number
  featureNumber?: number
  onEpicClick?: () => void
  onFeatureClick?: () => void
}
```

Import the helper and update the pill text:

```typescript
import { formatEntityNumber } from '../utils/format'

// In the epic pill span:
{epicNumber ? `${formatEntityNumber('epic', epicNumber)} ${epicTitle}` : epicTitle}

// In the feature pill span:
{featureNumber ? `${formatEntityNumber('feature', featureNumber)} ${featureTitle}` : featureTitle}
```

The new props are optional so existing usages without numbers still work.

- [ ] **Step 7: Update DetailPanel to show numbers**

In `DetailPanel.tsx`, import the helper:

```typescript
import { formatEntityNumber } from '../utils/format'
```

In `EpicDetail`, update the title:

```typescript
<h2 className="detail-title">
  {data.number > 0 && <span className="entity-number">{formatEntityNumber('epic', data.number)} </span>}
  {data.title}
</h2>
```

Add `number` to the `EpicData`, `FeatureData`, and `TaskData` interfaces (optional, `number?: number`).

In `FeatureDetail`, update the title similarly with `formatEntityNumber('feature', data.number)`.

In `TaskDetail`, update the title with `formatEntityNumber('task', data.number)`.

- [ ] **Step 8: Update App.tsx to pass numbers to DetailPanel**

In `App.tsx`, update the `openDetail` function to include `number` in the data objects it builds:

For epic detail: add `number: epicEntry.epic.number`
For feature detail: add `number: feat.feature.number`
For task detail from board: add `number: task.number` (TaskCard now has `number`)
For task detail from backlog: add `number: t.number` (BacklogTask now has `number`)

Also update `BreadcrumbPills` usage in `TaskCard.tsx` to pass `epicNumber` and `featureNumber` — but TaskCard only has `epic_title`/`feature_title`/`epic_color`, not the numbers. To avoid changing the board API response shape further, skip numbers in TaskCard breadcrumb pills for now. The numbers show in the BacklogTree and DetailPanel.

- [ ] **Step 9: Update test mock data**

Add `number: 1` (or appropriate values) to mock data in:
- `BacklogTree.test.tsx` — add `number` to epic, feature, and task objects
- `BreadcrumbPills.test.tsx` — add optional `epicNumber`/`featureNumber` props test
- `DetailPanel.test.tsx` — add `number` to data objects

- [ ] **Step 10: Run all frontend tests**

Run: `cd frontend && npx vitest run`
Expected: All pass

- [ ] **Step 11: TypeScript check**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 12: Commit**

```bash
git add frontend/src/utils/ frontend/src/components/ frontend/src/App.tsx
git commit -m "feat(frontend): display entity numbers in backlog tree, pills, and detail panel"
```

---

### Task 4: Run full quality gate

- [ ] **Step 1: Backend quality**

Run: `make quality`
Expected: PASSED

- [ ] **Step 2: Frontend tests**

Run: `cd frontend && npx tsc --noEmit && npx vitest run`
Expected: All pass

- [ ] **Step 3: Contract check**

Run: `make contract-check`
Expected: "Contract check passed"
