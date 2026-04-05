# F-18: Dependency Graph Visualization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add feature-level dependency graph visualization using Mermaid-to-Excalidraw rendering, with CRUD API endpoints, cycle detection, and SSE integration.

**Architecture:** Reuse existing `FeatureDependency` table (no migration). Add repository/service/route layers for dependency CRUD with cycle detection. Frontend renders Mermaid flowchart definition through `parseMermaidToExcalidraw()` into a read-only Excalidraw canvas. Lazy-loaded to avoid impacting board load time.

**Tech Stack:** Python/FastAPI (backend), TypeScript/React (frontend), `@excalidraw/excalidraw` + `@excalidraw/mermaid-to-excalidraw` (visualization)

---

### Task 1: Backend — ORM relationships and repository methods

**Files:**
- Modify: `src/board/models.py:60-78` (Feature model)
- Modify: `src/board/repository.py` (add dependency methods)
- Create: `tests/board/test_dependencies.py`

- [ ] **Step 1: Run existing tests to establish baseline**

```bash
uv run pytest tests/board/ -v --tb=short
```

- [ ] **Step 2: Add ORM relationships to Feature model**

In `src/board/models.py`, add to the `Feature` class after the `tasks` relationship:

```python
dependencies: Mapped[list[Feature]] = relationship(
    secondary="feature_dependencies",
    primaryjoin="Feature.id == feature_dependencies.c.feature_id",
    secondaryjoin="Feature.id == feature_dependencies.c.depends_on_id",
    lazy="selectin",
)
dependents: Mapped[list[Feature]] = relationship(
    secondary="feature_dependencies",
    primaryjoin="Feature.id == feature_dependencies.c.depends_on_id",
    secondaryjoin="Feature.id == feature_dependencies.c.feature_id",
    lazy="selectin",
    viewonly=True,
)
```

- [ ] **Step 3: Write failing tests for repository methods**

Create `tests/board/test_dependencies.py`:

```python
import pytest
from uuid import UUID
from httpx import AsyncClient


@pytest.fixture
async def project_with_features(client: AsyncClient):
    """Create a project with 3 features for dependency testing."""
    project = (await client.post("/api/v1/projects", json={"name": "dep-test"})).json()
    pid = project["id"]
    epic = (await client.post(f"/api/v1/projects/{pid}/epics", json={"title": "E1"})).json()
    eid = epic["id"]

    f1 = (await client.post(f"/api/v1/projects/{pid}/epics/{eid}/features", json={"title": "F-A"})).json()
    f2 = (await client.post(f"/api/v1/projects/{pid}/epics/{eid}/features", json={"title": "F-B"})).json()
    f3 = (await client.post(f"/api/v1/projects/{pid}/epics/{eid}/features", json={"title": "F-C"})).json()

    return {"project_id": pid, "features": [f1, f2, f3]}


async def test_add_dependency(client: AsyncClient, project_with_features):
    """Adding a dependency returns 201."""
    features = project_with_features["features"]
    resp = await client.post(
        f"/api/v1/features/{features[0]['id']}/dependencies",
        json={"depends_on_id": features[1]["id"]},
    )
    assert resp.status_code == 201


async def test_self_dependency_rejected(client: AsyncClient, project_with_features):
    """Cannot depend on self."""
    fid = project_with_features["features"][0]["id"]
    resp = await client.post(
        f"/api/v1/features/{fid}/dependencies",
        json={"depends_on_id": fid},
    )
    assert resp.status_code == 400


async def test_cycle_detection(client: AsyncClient, project_with_features):
    """Cannot create a cycle: A->B then B->A."""
    features = project_with_features["features"]
    # A depends on B
    resp1 = await client.post(
        f"/api/v1/features/{features[0]['id']}/dependencies",
        json={"depends_on_id": features[1]["id"]},
    )
    assert resp1.status_code == 201
    # B depends on A → cycle
    resp2 = await client.post(
        f"/api/v1/features/{features[1]['id']}/dependencies",
        json={"depends_on_id": features[0]["id"]},
    )
    assert resp2.status_code == 400
    assert "cycle" in resp2.json()["detail"].lower()


async def test_transitive_cycle_detection(client: AsyncClient, project_with_features):
    """Cannot create a transitive cycle: A->B->C then C->A."""
    features = project_with_features["features"]
    await client.post(f"/api/v1/features/{features[0]['id']}/dependencies", json={"depends_on_id": features[1]["id"]})
    await client.post(f"/api/v1/features/{features[1]['id']}/dependencies", json={"depends_on_id": features[2]["id"]})
    # C depends on A → transitive cycle
    resp = await client.post(
        f"/api/v1/features/{features[2]['id']}/dependencies",
        json={"depends_on_id": features[0]["id"]},
    )
    assert resp.status_code == 400
    assert "cycle" in resp.json()["detail"].lower()


async def test_duplicate_dependency_rejected(client: AsyncClient, project_with_features):
    """Cannot add the same dependency twice."""
    features = project_with_features["features"]
    await client.post(f"/api/v1/features/{features[0]['id']}/dependencies", json={"depends_on_id": features[1]["id"]})
    resp = await client.post(
        f"/api/v1/features/{features[0]['id']}/dependencies",
        json={"depends_on_id": features[1]["id"]},
    )
    assert resp.status_code == 409


async def test_remove_dependency(client: AsyncClient, project_with_features):
    """Removing a dependency returns 204."""
    features = project_with_features["features"]
    await client.post(f"/api/v1/features/{features[0]['id']}/dependencies", json={"depends_on_id": features[1]["id"]})
    resp = await client.delete(f"/api/v1/features/{features[0]['id']}/dependencies/{features[1]['id']}")
    assert resp.status_code == 204


async def test_dependency_graph_endpoint(client: AsyncClient, project_with_features):
    """Graph endpoint returns nodes and edges."""
    pid = project_with_features["project_id"]
    features = project_with_features["features"]
    await client.post(f"/api/v1/features/{features[0]['id']}/dependencies", json={"depends_on_id": features[1]["id"]})

    resp = await client.get(f"/api/v1/projects/{pid}/dependency-graph")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["nodes"]) == 3  # all features included
    assert len(data["edges"]) == 1


async def test_diamond_no_cycle(client: AsyncClient, project_with_features):
    """Diamond pattern (A->B, A->C, B->C) is valid — not a cycle."""
    features = project_with_features["features"]
    r1 = await client.post(f"/api/v1/features/{features[0]['id']}/dependencies", json={"depends_on_id": features[1]["id"]})
    r2 = await client.post(f"/api/v1/features/{features[0]['id']}/dependencies", json={"depends_on_id": features[2]["id"]})
    r3 = await client.post(f"/api/v1/features/{features[1]['id']}/dependencies", json={"depends_on_id": features[2]["id"]})
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r3.status_code == 201
```

- [ ] **Step 4: Add repository methods**

In `src/board/repository.py`, add these methods to `BoardRepository`:

```python
from src.board.models import FeatureDependency

async def add_dependency(self, feature_id: UUID, depends_on_id: UUID) -> None:
    dep = FeatureDependency(feature_id=feature_id, depends_on_id=depends_on_id)
    self._session.add(dep)
    await self._session.commit()

async def remove_dependency(self, feature_id: UUID, depends_on_id: UUID) -> bool:
    dep = await self._session.get(FeatureDependency, (feature_id, depends_on_id))
    if dep is None:
        return False
    await self._session.delete(dep)
    await self._session.commit()
    return True

async def get_dependency_exists(self, feature_id: UUID, depends_on_id: UUID) -> bool:
    dep = await self._session.get(FeatureDependency, (feature_id, depends_on_id))
    return dep is not None

async def get_all_dependencies(self, project_id: UUID) -> list[tuple[UUID, UUID]]:
    """Get all (feature_id, depends_on_id) pairs for features in this project."""
    result = await self._session.execute(
        select(FeatureDependency.feature_id, FeatureDependency.depends_on_id)
        .join(Feature, FeatureDependency.feature_id == Feature.id)
        .join(Epic, Feature.epic_id == Epic.id)
        .where(Epic.project_id == project_id)
    )
    return [(row[0], row[1]) for row in result.all()]

async def get_feature_dependencies(self, feature_id: UUID) -> list[UUID]:
    """Get IDs of features that this feature depends on."""
    result = await self._session.execute(
        select(FeatureDependency.depends_on_id)
        .where(FeatureDependency.feature_id == feature_id)
    )
    return [row[0] for row in result.all()]
```

- [ ] **Step 5: Run tests — they should still fail (no routes yet)**

```bash
uv run pytest tests/board/test_dependencies.py -v --tb=short
```

Expected: connection errors or 404s (routes not added yet). This validates the test fixtures work.

- [ ] **Step 6: Commit repository layer**

```bash
git add src/board/models.py src/board/repository.py tests/board/test_dependencies.py
git commit -m "feat(board): add dependency ORM relationships and repository methods"
```

---

### Task 2: Backend — Service layer with cycle detection

**Files:**
- Modify: `src/board/services.py`

- [ ] **Step 1: Add cycle detection to BoardService**

In `src/board/services.py`, add:

```python
async def has_cycle(self, feature_id: UUID, depends_on_id: UUID) -> bool:
    """DFS from depends_on_id's own dependencies. If we reach feature_id, there's a cycle."""
    visited: set[UUID] = set()
    stack = [depends_on_id]
    while stack:
        current = stack.pop()
        if current == feature_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        deps = await self._repo.get_feature_dependencies(current)
        stack.extend(deps)
    return False

async def add_dependency(self, feature_id: UUID, depends_on_id: UUID) -> None:
    """Add dependency with full validation."""
    if feature_id == depends_on_id:
        raise ValueError("A feature cannot depend on itself")

    # Both features must exist and be in the same project
    feature = await self._repo.get_feature(feature_id)
    depends_on = await self._repo.get_feature(depends_on_id)
    if feature is None or depends_on is None:
        raise ValueError("Feature not found")

    epic_a = await self._repo.get_epic(feature.epic_id)
    epic_b = await self._repo.get_epic(depends_on.epic_id)
    assert epic_a is not None and epic_b is not None
    if epic_a.project_id != epic_b.project_id:
        raise ValueError("Features must be in the same project")

    # Check for duplicate
    if await self._repo.get_dependency_exists(feature_id, depends_on_id):
        raise ValueError("DUPLICATE")

    # Check for cycle
    if await self.has_cycle(feature_id, depends_on_id):
        raise ValueError("Adding this dependency would create a cycle")

    await self._repo.add_dependency(feature_id, depends_on_id)

async def remove_dependency(self, feature_id: UUID, depends_on_id: UUID) -> bool:
    return await self._repo.remove_dependency(feature_id, depends_on_id)

async def get_dependency_graph(self, project_id: UUID) -> dict:
    """Return nodes + edges for the full project dependency graph."""
    epics = await self._repo.get_backlog_tree(project_id)
    edges = await self._repo.get_all_dependencies(project_id)

    nodes = []
    for epic in epics:
        for feature in epic.features:
            nodes.append({
                "id": str(feature.id),
                "number": feature.number,
                "title": feature.title,
                "status": feature.status,
                "epic_title": epic.title,
                "epic_color": epic.color,
            })

    edge_list = []
    # Build a number lookup for edge rendering
    number_map = {n["id"]: n["number"] for n in nodes}
    for feat_id, dep_id in edges:
        edge_list.append({
            "from_id": str(dep_id),
            "to_id": str(feat_id),
            "from_number": number_map.get(str(dep_id), 0),
            "to_number": number_map.get(str(feat_id), 0),
        })

    return {"nodes": nodes, "edges": edge_list}
```

- [ ] **Step 2: Commit service layer**

```bash
git add src/board/services.py
git commit -m "feat(board): add dependency service with cycle detection"
```

---

### Task 3: Backend — API routes and schemas

**Files:**
- Modify: `src/board/routes.py`
- Modify: `src/board/schemas.py`
- Modify: `src/shared/events.py`

- [ ] **Step 1: Add schemas**

In `src/board/schemas.py`, add after the existing schemas:

```python
# --- Dependencies ---

class DependencyCreate(BaseModel):
    depends_on_id: UUID

class DependencyGraphNode(BaseModel):
    id: UUID
    number: int
    title: str
    status: str
    epic_title: str
    epic_color: str

class DependencyGraphEdge(BaseModel):
    from_id: UUID
    to_id: UUID
    from_number: int
    to_number: int

class DependencyGraphResponse(BaseModel):
    nodes: list[DependencyGraphNode]
    edges: list[DependencyGraphEdge]
```

- [ ] **Step 2: Add event types**

In `src/shared/events.py`, add to `EventType`:

```python
DEPENDENCY_ADDED = "dependency_added"
DEPENDENCY_REMOVED = "dependency_removed"
```

- [ ] **Step 3: Add routes**

In `src/board/routes.py`, add imports and 3 new endpoints:

```python
from src.board.schemas import DependencyCreate, DependencyGraphResponse

# --- Dependencies ---

@router.get(
    "/projects/{project_id}/dependency-graph",
    response_model=DependencyGraphResponse,
)
async def get_dependency_graph(project_id: UUID, service: ServiceDep) -> dict:
    project = await service._repo.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return await service.get_dependency_graph(project_id)


@router.post("/features/{feature_id}/dependencies", status_code=201)
async def add_dependency(
    feature_id: UUID, body: DependencyCreate, service: ServiceDep
) -> dict[str, str]:
    try:
        await service.add_dependency(feature_id, body.depends_on_id)
    except ValueError as e:
        msg = str(e)
        if "DUPLICATE" in msg:
            raise HTTPException(status_code=409, detail="Dependency already exists")
        raise HTTPException(status_code=400, detail=str(e))
    # Resolve project_id for SSE event
    feature = await service._repo.get_feature(feature_id)
    assert feature is not None
    epic = await service._repo.get_epic(feature.epic_id)
    assert epic is not None
    await event_bus.publish(
        Event(
            type=EventType.DEPENDENCY_ADDED,
            project_id=epic.project_id,
            data={
                "feature_id": str(feature_id),
                "depends_on_id": str(body.depends_on_id),
            },
        )
    )
    return {"status": "created"}


@router.delete("/features/{feature_id}/dependencies/{depends_on_id}", status_code=204)
async def remove_dependency(
    feature_id: UUID, depends_on_id: UUID, service: ServiceDep
) -> None:
    # Resolve project_id before removal
    feature = await service._repo.get_feature(feature_id)
    if feature is None:
        raise HTTPException(status_code=404, detail="Feature not found")
    epic = await service._repo.get_epic(feature.epic_id)
    assert epic is not None
    project_id = epic.project_id
    removed = await service.remove_dependency(feature_id, depends_on_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Dependency not found")
    await event_bus.publish(
        Event(
            type=EventType.DEPENDENCY_REMOVED,
            project_id=project_id,
            data={
                "feature_id": str(feature_id),
                "depends_on_id": str(depends_on_id),
            },
        )
    )
```

- [ ] **Step 4: Run dependency tests**

```bash
uv run pytest tests/board/test_dependencies.py -v
```

Expected: All 8 tests pass.

- [ ] **Step 5: Run full backend tests**

```bash
uv run pytest tests/ -v
```

Expected: All existing + new tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/board/routes.py src/board/schemas.py src/shared/events.py
git commit -m "feat(board): add dependency graph API endpoints with SSE events"
```

---

### Task 4: Frontend — Install Excalidraw packages

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Install dependencies**

```bash
cd frontend && npm install @excalidraw/excalidraw @excalidraw/mermaid-to-excalidraw
```

- [ ] **Step 2: Verify build still works**

```bash
cd frontend && npx tsc --noEmit && npx vitest run
```

- [ ] **Step 3: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "deps(frontend): add excalidraw and mermaid-to-excalidraw"
```

---

### Task 5: Frontend — DependencyGraph component and hook

**Files:**
- Create: `frontend/src/components/DependencyGraph.tsx`
- Create: `frontend/src/components/DependencyGraph.css`
- Create: `frontend/src/hooks/useDependencyGraph.ts`
- Modify: `frontend/src/api/client.ts` (add graph API method)
- Modify: `frontend/src/api/types.ts` (add graph types, SSE events)
- Modify: `frontend/src/hooks/useSSE.ts` (add dependency events)

- [ ] **Step 1: Add API types**

In `frontend/src/api/types.ts`, add:

```typescript
// Dependency graph types (not yet in OpenAPI contract)
export interface DependencyGraphNode {
  id: string
  number: number
  title: string
  status: string
  epic_title: string
  epic_color: string
}

export interface DependencyGraphEdge {
  from_id: string
  to_id: string
  from_number: number
  to_number: number
}

export interface DependencyGraphResponse {
  nodes: DependencyGraphNode[]
  edges: DependencyGraphEdge[]
}
```

Add `'dependency_added' | 'dependency_removed'` to the `SSEEvent` type union.

- [ ] **Step 2: Add API client methods**

In `frontend/src/api/client.ts`, add:

```typescript
import type { ..., DependencyGraphResponse } from './types'

// Dependencies
getDependencyGraph: (projectId: string) =>
  fetchJSON<DependencyGraphResponse>(`/projects/${projectId}/dependency-graph`),
addDependency: (featureId: string, dependsOnId: string) =>
  fetchJSON<{ status: string }>(`/features/${featureId}/dependencies`, {
    method: 'POST',
    body: JSON.stringify({ depends_on_id: dependsOnId }),
  }),
removeDependency: (featureId: string, dependsOnId: string) =>
  fetch(`${BASE_URL}/features/${featureId}/dependencies/${dependsOnId}`, {
    method: 'DELETE',
  }),
```

- [ ] **Step 3: Add SSE event types**

In `frontend/src/hooks/useSSE.ts`, add `'dependency_added'` and `'dependency_removed'` to the `eventTypes` array.

- [ ] **Step 4: Create useDependencyGraph hook**

Create `frontend/src/hooks/useDependencyGraph.ts`:

```typescript
import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { DependencyGraphResponse, SSEEvent } from '../api/types'
import { useSSE } from './useSSE'

export function useDependencyGraph(projectId: string | null) {
  const [graph, setGraph] = useState<DependencyGraphResponse | null>(null)
  const [loading, setLoading] = useState(false)

  const fetchGraph = useCallback(async () => {
    if (!projectId) return
    setLoading(true)
    try {
      const data = await api.getDependencyGraph(projectId)
      setGraph(data)
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => { fetchGraph() }, [fetchGraph])

  useSSE(projectId, useCallback((event: SSEEvent) => {
    if (event.type === 'dependency_added' || event.type === 'dependency_removed'
        || event.type === 'feature_created' || event.type === 'feature_deleted') {
      fetchGraph()
    }
  }, [fetchGraph]))

  return { graph, loading, refetch: fetchGraph }
}
```

- [ ] **Step 5: Create DependencyGraph component**

Create `frontend/src/components/DependencyGraph.tsx`:

The component:
1. Takes `projectId` and `onItemClick` props
2. Uses `useDependencyGraph` hook to fetch data
3. Builds a Mermaid `flowchart LR` string from nodes/edges (grouped by epic as subgraphs)
4. Calls `parseMermaidToExcalidraw()` to convert to Excalidraw elements
5. Renders via lazy-loaded `<Excalidraw>` component in `viewModeEnabled` mode
6. Handles `onLinkOpen` to call `onItemClick('feature', featureId)` for node clicks
7. Shows loading state and empty state ("No features yet")

Key implementation details:
- Use `React.lazy(() => import("@excalidraw/excalidraw"))` for code splitting
- Import `@excalidraw/excalidraw/index.css` in the component
- The Mermaid definition uses `click FN "/features/UUID"` syntax for link callbacks
- Excalidraw's `onLinkOpen` event fires with the link URL — parse the feature UUID from it
- Set `viewModeEnabled={true}` to prevent user edits
- Use `theme="dark"` to match the cloglog dark theme
- Wrap in `<Suspense fallback={...}>` for loading state

- [ ] **Step 6: Create DependencyGraph.css**

Create `frontend/src/components/DependencyGraph.css` with styles for:
- Full-height container (fill available space)
- Loading spinner
- Empty state message

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/DependencyGraph.tsx frontend/src/components/DependencyGraph.css \
  frontend/src/hooks/useDependencyGraph.ts frontend/src/api/client.ts \
  frontend/src/api/types.ts frontend/src/hooks/useSSE.ts
git commit -m "feat(frontend): add DependencyGraph component with Excalidraw rendering"
```

---

### Task 6: Frontend — Routing and view toggle

**Files:**
- Modify: `frontend/src/router.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/BoardHeader.tsx`

- [ ] **Step 1: Add dependencies route**

In `frontend/src/router.tsx`, add:

```typescript
{ path: '/projects/:projectId/dependencies', element: <App /> },
```

- [ ] **Step 2: Update App.tsx to detect dependencies view**

In `frontend/src/App.tsx`:
- Parse a new `view` from the URL (if path ends with `/dependencies`)
- Conditionally render `<DependencyGraph>` instead of `<Board>` when on the dependencies route
- Pass `onItemClick` handler to DependencyGraph

- [ ] **Step 3: Add view toggle to BoardHeader**

In `frontend/src/components/BoardHeader.tsx`:
- Add tab-style toggle between "Board" and "Dependencies"
- Use `useNavigate()` to switch between `/projects/:id` and `/projects/:id/dependencies`
- Highlight the active tab based on current route

- [ ] **Step 4: Run frontend tests**

```bash
cd frontend && npx vitest run
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/router.tsx frontend/src/App.tsx frontend/src/components/BoardHeader.tsx
git commit -m "feat(frontend): add Dependencies tab with route toggle"
```

---

### Task 7: Frontend — Dependency management in DetailPanel

**Files:**
- Modify: `frontend/src/components/DetailPanel.tsx`
- Modify: `frontend/src/App.tsx` (pass dependency data to feature detail)

- [ ] **Step 1: Extend FeatureData with dependency info**

In `DetailPanel.tsx`, update `FeatureData` interface:

```typescript
interface FeatureData {
  // ... existing fields ...
  dependencies?: Array<{ id: string; title: string; number: number }>
  dependents?: Array<{ id: string; title: string; number: number }>
  all_features?: Array<{ id: string; title: string; number: number }>
}
```

- [ ] **Step 2: Add Dependencies section to FeatureDetail**

After the DocumentChips in `FeatureDetail`, add a new section:

```
Dependencies
  Depends on: [list of features with [x] remove buttons]
  Blocks: [list of features, read-only]
  [+ Add dependency] → dropdown of available features
```

Implementation:
- "Remove" button calls `api.removeDependency(featureId, depId)` then refetches
- "Add" button shows a `<select>` filtered to exclude self and already-depended-on features
- On add, calls `api.addDependency(featureId, selectedId)` then refetches

- [ ] **Step 3: Wire dependency data in App.tsx**

In `buildFeatureDetail()`, include dependency info from the graph data or a separate API call. The simplest approach: fetch the dependency graph once and look up dependencies for the selected feature.

- [ ] **Step 4: Run frontend tests**

```bash
cd frontend && npx vitest run
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/DetailPanel.tsx frontend/src/App.tsx
git commit -m "feat(frontend): add dependency management to feature detail panel"
```

---

### Task 8: Frontend tests

**Files:**
- Create: `frontend/src/components/__tests__/DependencyGraph.test.tsx`

- [ ] **Step 1: Write DependencyGraph component tests**

Tests to cover:
- Generates correct Mermaid definition from graph data (nodes grouped by epic, edges present)
- Renders loading state while fetching
- Shows empty state when no features exist
- Click callback fires `onItemClick` with correct feature ID

- [ ] **Step 2: Write useDependencyGraph hook tests**

Tests to cover:
- Fetches graph data on mount
- Refetches on SSE dependency events

- [ ] **Step 3: Run all frontend tests**

```bash
cd frontend && npx vitest run
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/__tests__/DependencyGraph.test.tsx
git commit -m "test(frontend): add DependencyGraph component and hook tests"
```

---

### Task 9: Quality gate and final verification

- [ ] **Step 1: Run full quality gate**

```bash
make quality
```

Expected: All checks pass (lint, typecheck, tests, contract).

- [ ] **Step 2: Run backend tests with verbose output**

```bash
uv run pytest tests/ -v
```

- [ ] **Step 3: Run frontend tests**

```bash
cd frontend && npx vitest run
```

- [ ] **Step 4: Fix any issues found**

- [ ] **Step 5: Final commit if needed, then push and create PR**

Use bot identity (see CLAUDE.md). PR should include:
- Summary of all changes
- Test report with delta (pre-existing count, new tests added, final count)
- Screenshot of the dependency graph view (if possible)
