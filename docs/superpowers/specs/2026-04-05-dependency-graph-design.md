# F-18: Dependency Graph Visualization

**Date:** 2026-04-05
**Feature:** F-18 Dependency Graph Visualization (Epic: Board Redesign)
**Scope:** T-92 (design spec), T-93 (implementation plan), T-94 (implementation)

## Problem

The cloglog board shows epics, features, and tasks as flat lists (backlog tree) or status columns (kanban). There is no way to see **which features block which other features**. The user cannot answer: "What's bottlenecked?", "What's ready to work on?", or "What's the critical path?" without manually cross-referencing feature descriptions.

A `FeatureDependency` table already exists in the database (`feature_id` depends on `depends_on_id`, both FK to `features.id`) but is completely unused: no repository methods, no API endpoints, no UI.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Dependency scope | Feature-level only | Features are the planning unit. Epics are grouping, tasks are execution. Feature-level keeps the graph manageable (dozens of nodes, not hundreds). Task-level blocking can be added independently via F-11. |
| Visualization library | Mermaid-to-Excalidraw | `mermaid@^11.14.0` already installed. Add `@excalidraw/excalidraw` + `@excalidraw/mermaid-to-excalidraw`. Excalidraw's hand-drawn aesthetic is vastly better than Mermaid's default SVG. Flowcharts get full native shape conversion (not image fallback). |
| Graph layout | Mermaid `flowchart LR` → Excalidraw canvas | Define graph in Mermaid syntax (left-to-right DAG), convert to Excalidraw elements via `parseMermaidToExcalidraw()`. Excalidraw handles rendering with pan/zoom built-in. |
| Bundle size | Lazy-load Excalidraw component | `@excalidraw/excalidraw` is ~47MB unpacked. Mitigate with `React.lazy()` + code splitting — only loaded when user navigates to the Dependencies tab. No impact on initial board load. |
| UI placement | New "Dependencies" tab alongside the existing board view | The board has a tabbed structure conceptually (backlog tree + kanban columns). Adding a dependency graph as a peer view keeps the existing board clean. Accessible via URL routing (`/projects/:id/dependencies`). |
| Node styling | Color-coded by epic, status shown via node shape | Reuse existing epic colors for grouping. Excalidraw renders with hand-drawn aesthetic. Status conveyed through Mermaid class definitions that map to fill colors (green=done, blue=in-progress, gray=planned). |
| Node interaction | Click node to open detail panel | Excalidraw's `onLinkOpen` callback fires when users click nodes with links. Map feature IDs to the existing `onItemClick('feature', id)` handler. Excalidraw provides built-in pan/zoom. |
| Dependency CRUD | API endpoints + detail panel UI | Add/remove dependencies from the feature detail panel. Simple dropdown to select target feature. No drag-to-connect in the graph (complexity not justified). |
| Cycle detection | Server-side on create | Reject dependency creation if it would form a cycle. Simple DFS from the target back to the source. Prevents impossible dependency chains. |
| SSE integration | Emit events on dependency changes | `dependency_added` and `dependency_removed` events trigger graph refetch. Follows existing SSE pattern. |

## Data Model

### Existing Table (no migration needed)

```sql
-- Already exists from initial migration (318e2b5f41df)
CREATE TABLE feature_dependencies (
    feature_id UUID REFERENCES features(id),
    depends_on_id UUID REFERENCES features(id),
    PRIMARY KEY (feature_id, depends_on_id)
);
```

Semantics: `(feature_id=A, depends_on_id=B)` means "Feature A depends on Feature B" (A cannot start until B is done). In graph terms: edge from B to A (B blocks A).

### ORM Relationships (add to Feature model)

```python
# In Feature model
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

No new migration required. The table already exists.

## API Endpoints

All under the Board context (dependencies are a Board concept).

### `GET /projects/{project_id}/dependency-graph`

Returns the full dependency graph for rendering.

**Response:**
```json
{
  "nodes": [
    {
      "id": "uuid",
      "number": 18,
      "title": "Dependency Graph Visualization",
      "status": "planned",
      "epic_title": "Board Redesign",
      "epic_color": "#7c3aed"
    }
  ],
  "edges": [
    {
      "from_id": "uuid-of-dependency",
      "to_id": "uuid-of-dependent",
      "from_number": 11,
      "to_number": 18
    }
  ]
}
```

Nodes include all features in the project (even those without dependencies) so the graph shows the full picture. Isolated features appear as disconnected nodes grouped by epic.

### `POST /features/{feature_id}/dependencies`

Add a dependency.

**Request:**
```json
{ "depends_on_id": "uuid-of-upstream-feature" }
```

**Response:** `201 Created` with the updated dependency list for the feature.

**Validation:**
- Both features must exist and belong to the same project
- Cannot self-depend
- Cannot create cycles (DFS check)
- Cannot duplicate existing dependency

### `DELETE /features/{feature_id}/dependencies/{depends_on_id}`

Remove a dependency.

**Response:** `204 No Content`

### SSE Events

```python
DEPENDENCY_ADDED = "dependency_added"
DEPENDENCY_REMOVED = "dependency_removed"
```

Event data: `{"feature_id": "...", "depends_on_id": "...", "project_id": "..."}`

Frontend handles these by refetching the dependency graph (same pattern as other entity events).

## Backend: Repository Methods

Add to `BoardRepository`:

```python
async def add_dependency(self, feature_id: UUID, depends_on_id: UUID) -> None
async def remove_dependency(self, feature_id: UUID, depends_on_id: UUID) -> bool
async def get_dependencies(self, feature_id: UUID) -> list[Feature]
async def get_dependents(self, feature_id: UUID) -> list[Feature]
async def get_dependency_graph(self, project_id: UUID) -> tuple[list[Feature], list[tuple[UUID, UUID]]]
async def has_cycle(self, feature_id: UUID, depends_on_id: UUID) -> bool
```

The `has_cycle` method performs a DFS: starting from `depends_on_id`, follow its own dependencies recursively. If we reach `feature_id`, there's a cycle. This runs before inserting a new dependency row.

The `get_dependency_graph` method loads all features for a project and all dependency edges in two queries (no N+1).

## Backend: Service Methods

Add to `BoardService`:

```python
async def add_dependency(self, feature_id: UUID, depends_on_id: UUID) -> None:
    """Add dependency with validation (same project, no self, no cycle, no dup)."""

async def remove_dependency(self, feature_id: UUID, depends_on_id: UUID) -> None:
    """Remove dependency."""

async def get_dependency_graph(self, project_id: UUID) -> dict:
    """Return nodes + edges for the full project graph."""
```

## Frontend: Dependency Graph View

### New Dependencies

```json
{
  "@excalidraw/excalidraw": "^0.18.0",
  "@excalidraw/mermaid-to-excalidraw": "^1.1.0"
}
```

### New Component: `DependencyGraph.tsx`

Converts a Mermaid flowchart definition to Excalidraw elements and renders them on an interactive canvas.

**Pipeline:**
1. Build Mermaid `flowchart LR` string from graph API response (nodes grouped by epic, edges for dependencies)
2. Call `parseMermaidToExcalidraw(mermaidDef)` to get Excalidraw element skeletons
3. Convert skeletons to full elements using `convertToExcalidrawElements()`
4. Render via `<Excalidraw>` component in view-only mode

**Lazy loading:**
```typescript
const Excalidraw = React.lazy(() =>
  import("@excalidraw/excalidraw").then(mod => ({ default: mod.Excalidraw }))
)
```

The component is wrapped in `<Suspense fallback={<LoadingSpinner />}>` so the ~47MB Excalidraw bundle only loads when the user navigates to the Dependencies tab. No impact on board load time.

**Mermaid definition generation:**
```
flowchart LR
  subgraph E1["Board Redesign"]
    style E1 fill:transparent,stroke:#7c3aed
    F1["F-1 Grouped Backlog"]:::done
    F13["F-13 UI Improvements"]:::in_progress
    F18["F-18 Dependency Graph"]:::planned
  end
  subgraph E4["Operations"]
    style E4 fill:transparent,stroke:#10b981
    F11["F-11 Dependency Enforcement"]:::planned
  end
  F11 --> F18
  F1 --> F13

  classDef done fill:#059669,stroke:#047857,color:#fff
  classDef in_progress fill:#2563eb,stroke:#1d4ed8,color:#fff
  classDef planned fill:#374151,stroke:#4b5563,color:#d1d5db
```

This Mermaid definition is passed to `parseMermaidToExcalidraw()` which produces native Excalidraw rectangles, arrows, and text — rendered with Excalidraw's hand-drawn visual style.

**Interaction:**
- **Pan/zoom:** Built into Excalidraw canvas (scroll to zoom, drag to pan)
- **Click a node:** Excalidraw supports link callbacks via `onLinkOpen`. Mermaid `click` directives are converted to Excalidraw links. Intercept `onLinkOpen` to call `onItemClick('feature', featureId)` and open the detail panel.
- **Read-only mode:** `viewModeEnabled={true}` prevents users from editing the graph. The graph is a computed visualization, not a user-editable canvas.

### Component Props:
```typescript
interface DependencyGraphProps {
  projectId: string
  onItemClick: (type: 'epic' | 'feature' | 'task', id: string) => void
}
```

### New Hook: `useDependencyGraph.ts`

```typescript
function useDependencyGraph(projectId: string | null) {
  // Fetches GET /projects/{id}/dependency-graph
  // Returns { nodes, edges, loading, refetch }
  // Listens for SSE dependency_added/dependency_removed events to refetch
}
```

### Routing

Add route in `main.tsx`:
```
/projects/:projectId/dependencies → show DependencyGraph instead of Board
```

Add a tab/toggle in `BoardHeader.tsx` to switch between Board view and Dependencies view.

### Feature Detail Panel: Dependency Management

Add a "Dependencies" section to the feature detail view in `DetailPanel.tsx`:

```
Dependencies
  Depends on: F-11 Dependency Enforcement [x]
  Blocks: (none)
  [+ Add dependency] → dropdown of features in same project
```

- Shows both incoming (depends on) and outgoing (blocks) relationships
- Click [x] to remove a dependency (calls DELETE endpoint)
- "Add dependency" shows a dropdown/autocomplete of features filtered to the same project
- Dropdown excludes: self, already-depended-on features

## Schemas

### New Pydantic Schemas

```python
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

class FeatureDependencyResponse(BaseModel):
    feature_id: UUID
    depends_on: list[FeatureResponse]
    dependents: list[FeatureResponse]
```

## Testing Strategy

### Backend Tests

**Unit tests (cycle detection):**
- Test `has_cycle` with: no cycle, direct cycle (A depends on B, B depends on A), transitive cycle (A→B→C→A), diamond (no cycle)

**Integration tests (API endpoints):**
- `POST /features/{id}/dependencies`: success, self-depend rejection, cycle rejection, duplicate rejection, cross-project rejection
- `DELETE /features/{id}/dependencies/{id}`: success, not-found
- `GET /projects/{id}/dependency-graph`: empty graph, graph with edges, isolated nodes included

**SSE tests:**
- Verify `dependency_added` and `dependency_removed` events are emitted

### Frontend Tests

**DependencyGraph component:**
- Generates correct Mermaid definition from graph data
- Renders Excalidraw canvas (lazy-loaded) with nodes and edges
- Shows empty state when no features exist
- Click callback fires `onItemClick` with correct feature ID via `onLinkOpen`

**useDependencyGraph hook:**
- Fetches graph data on mount
- Refetches on SSE events

**DetailPanel dependency section:**
- Shows "depends on" and "blocks" lists
- Add dependency triggers POST request
- Remove dependency triggers DELETE request

## Files Changed

| File | Change |
|------|--------|
| `src/board/models.py` | Add `dependencies` and `dependents` relationships to Feature |
| `src/board/repository.py` | Add dependency CRUD and graph query methods |
| `src/board/services.py` | Add dependency management with cycle detection |
| `src/board/routes.py` | Add 3 new endpoints (graph, add dep, remove dep) |
| `src/board/schemas.py` | Add dependency-related schemas |
| `src/shared/events.py` | Add `DEPENDENCY_ADDED`, `DEPENDENCY_REMOVED` event types |
| `frontend/src/components/DependencyGraph.tsx` | New component: Mermaid-based graph renderer |
| `frontend/src/components/DependencyGraph.css` | Styles for graph container and node states |
| `frontend/src/hooks/useDependencyGraph.ts` | New hook for graph data fetching + SSE |
| `frontend/src/hooks/useSSE.ts` | Add dependency event types |
| `frontend/src/components/DetailPanel.tsx` | Add dependency management section to feature view |
| `frontend/src/components/BoardHeader.tsx` | Add Board/Dependencies tab toggle |
| `frontend/src/App.tsx` | Add `/dependencies` route |
| `frontend/src/main.tsx` | Register new route |
| `tests/board/test_dependencies.py` | New: cycle detection unit tests |
| `tests/board/test_dependency_routes.py` | New: API endpoint integration tests |
| `frontend/src/components/__tests__/DependencyGraph.test.tsx` | New: component tests |
