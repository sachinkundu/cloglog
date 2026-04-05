# F-20: Drag-and-Drop Backlog Prioritization

**Date:** 2026-04-05
**Feature:** F-20 Drag-and-Drop Backlog Prioritization (Epic: Board Redesign)

## Problem

The backlog tree displays epics, features, and tasks in a fixed order determined by their `position` field (all default to 0). Users have no way to reorder items to reflect priority — what they want to focus on next should appear at the top. Currently, the only way to change order is through direct API calls, which is not a viable user workflow.

## Current State

### Backend
- **Position fields exist** on all three models (`Epic.position`, `Feature.position`, `Task.position`) as `int` with `default=0`.
- **Backlog endpoint** (`GET /projects/{project_id}/backlog`) already sorts by position: epics by `Epic.position`, features by `Feature.position`, tasks by `Task.position`.
- **Task PATCH exists** (`PATCH /tasks/{task_id}`) with `TaskUpdate` schema that already accepts `position`.
- **No Epic/Feature PATCH endpoints** — these need to be added.
- **No batch reorder endpoint** — individual PATCH calls would cause N requests per drag.

### Frontend
- **BacklogTree.tsx** renders the hierarchy: Epic → Feature → Task.
- **No drag library installed** — `package.json` has only React, react-router-dom, react-markdown, remark-gfm, mermaid.
- **CSS-only styling** — no component library (Tailwind, MUI, etc.).
- **API client** (`api/client.ts`) has no update methods for epic/feature position.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| DnD library | **@dnd-kit** | See library comparison below |
| Reorder scope | Same-level only | Epics reorder among epics, features within their epic, tasks within their feature. No cross-parent moves. |
| Position strategy | Integer gaps (multiples of 1000) | Simple, avoids fractional positions, allows many insertions before reindex needed |
| API design | Batch reorder endpoint per entity type | Single request updates all affected positions, avoids race conditions |
| Optimistic UI | Yes, revert on failure | Instant visual feedback; roll back if server rejects |
| SSE integration | Emit position_changed event | Other clients see reorder in real-time |

## Library Comparison

### Option 1: @dnd-kit (Recommended)

**Pros:**
- Modern, actively maintained, built for React
- Composable architecture — `@dnd-kit/core` + `@dnd-kit/sortable` for our exact use case
- Excellent accessibility out of the box (keyboard DnD, screen reader announcements)
- Small bundle (~12KB gzipped for core + sortable)
- First-class support for nested sortable lists (our epic → feature → task hierarchy)
- Works with any styling approach (perfect for our CSS-only setup)
- Supports both mouse and touch

**Cons:**
- Slightly more setup code than react-beautiful-dnd (but more flexible)

### Option 2: react-beautiful-dnd

**Pros:**
- Very popular, well-documented
- Simple API for basic sortable lists

**Cons:**
- **Unmaintained** — last release was 2021, marked as deprecated by Atlassian
- Nested sortable lists are poorly supported (a known pain point)
- React 19 compatibility uncertain
- Atlassian themselves moved to a new library (Pragmatic drag and drop)

### Option 3: Native HTML5 Drag API

**Pros:**
- Zero dependencies

**Cons:**
- No accessibility support (keyboard users cannot drag)
- Inconsistent behavior across browsers
- No built-in animations or visual feedback
- Significant implementation effort for sortable lists
- Touch support requires additional work

### Decision: @dnd-kit

@dnd-kit is the clear choice. It's the modern standard for React DnD, handles our nested sortable list requirement natively, provides accessibility for free, and has a small footprint. react-beautiful-dnd is deprecated and struggles with nested lists. Native HTML5 drag fails on accessibility.

## Backend Changes

### New Schemas

```python
# In src/board/schemas.py

class EpicUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    bounded_context: str | None = None
    context_description: str | None = None
    position: int | None = None

class FeatureUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    position: int | None = None

class ReorderItem(BaseModel):
    id: UUID
    position: int

class ReorderRequest(BaseModel):
    items: list[ReorderItem]
```

### New Endpoints

#### PATCH /epics/{epic_id}
Update an epic's mutable fields (title, description, position). Mirrors the existing `PATCH /tasks/{task_id}` pattern.

#### PATCH /features/{feature_id}
Update a feature's mutable fields (title, description, position). Same pattern.

#### POST /projects/{project_id}/epics/reorder
Batch update epic positions within a project. Accepts a list of `{id, position}` pairs. Validates all IDs belong to the project. Updates positions in a single transaction.

#### POST /projects/{project_id}/epics/{epic_id}/features/reorder
Batch update feature positions within an epic. Same pattern.

#### POST /features/{feature_id}/tasks/reorder
Batch update task positions within a feature. Same pattern.

### Position Strategy

- New items get `position = max_position + 1000` (or 0 if first).
- On reorder, recalculate positions for all items in the list as `index * 1000`.
- The batch reorder endpoint receives the full ordered list of IDs with new positions.
- Single transaction ensures consistency.

### SSE Events

Add new event types for position changes:
- `EPIC_REORDERED` — epics within a project were reordered
- `FEATURE_REORDERED` — features within an epic were reordered
- `TASK_REORDERED` — tasks within a feature were reordered

These events trigger a backlog refetch on other connected clients.

## Frontend Changes

### Dependencies

```bash
cd frontend && npm install @dnd-kit/core @dnd-kit/sortable @dnd-kit/utilities
```

### BacklogTree.tsx Modifications

The BacklogTree component needs three levels of sortable containers:

1. **Epic level**: `<SortableContext>` wrapping the list of epic items
2. **Feature level**: `<SortableContext>` wrapping features within each expanded epic
3. **Task level**: `<SortableContext>` wrapping tasks within each expanded feature

Each draggable item gets:
- A drag handle (grip icon on the left side of the item)
- Visual feedback during drag (opacity reduction, drop placeholder)
- Restricted axis movement (vertical only — `restrictToVerticalAxis` modifier)

### Drag Handle Design

- Small grip icon (⠿ or similar CSS dots pattern) appears on hover to the left of each item
- Always visible on touch devices
- Drag only initiates from the handle — clicking the item title still navigates to detail panel
- Handle is the keyboard-focusable element for accessibility

### Optimistic Updates

1. User drags an item to a new position
2. Frontend immediately reorders the local state
3. Frontend sends batch reorder request to backend
4. On success: no-op (state already correct)
5. On failure: revert to pre-drag state, show error toast

### API Client Additions

```typescript
// In api/client.ts
reorderEpics: (projectId: string, items: {id: string, position: number}[]) =>
  fetchJSON(`/projects/${projectId}/epics/reorder`, {
    method: 'POST',
    body: JSON.stringify({ items }),
  }),

reorderFeatures: (projectId: string, epicId: string, items: {id: string, position: number}[]) =>
  fetchJSON(`/projects/${projectId}/epics/${epicId}/features/reorder`, {
    method: 'POST',
    body: JSON.stringify({ items }),
  }),

reorderTasks: (featureId: string, items: {id: string, position: number}[]) =>
  fetchJSON(`/features/${featureId}/tasks/reorder`, {
    method: 'POST',
    body: JSON.stringify({ items }),
  }),
```

### SSE Handler

On receiving a reorder event, refetch the backlog to get the updated order. This is simpler and more reliable than trying to apply position deltas client-side.

## Accessibility

@dnd-kit provides these out of the box:
- **Keyboard support**: Tab to focus drag handle → Space to pick up → Arrow keys to move → Space to drop → Escape to cancel
- **Screen reader announcements**: "Picked up item X. Item X is now in position Y of Z." etc.
- **Focus management**: Focus returns to the dropped item after a drag operation

Custom additions:
- Drag handles have `aria-label="Reorder {item title}"`
- Sortable lists have `aria-label="Reorderable {entity type} list"`

## Testing

### Backend Tests
- Unit tests for reorder endpoints (happy path, invalid IDs, empty list)
- Test position persistence after reorder
- Test that positions are correctly recalculated (gap strategy)
- Test SSE event emission on reorder

### Frontend Tests
- Component test: drag handle renders for each item
- Component test: items reorder visually on drag
- Component test: API call fires with correct positions after drop
- Component test: optimistic revert on API failure
- Accessibility: keyboard navigation through drag handles

## Non-Goals

- **Cross-parent drag** (moving a feature to a different epic, or a task to a different feature) — this is a different feature with different UX implications
- **Drag to change status** (dragging a task from backlog to in_progress column) — status changes happen through the existing task update flow
- **Position-based agent scheduling** — position is purely visual priority for the user
- **Undo/redo** — standard browser behavior; not implementing custom undo stack
