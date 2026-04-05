# Design Spec: Board Search Widget (F-21)

**Date:** 2026-04-05
**Feature:** F-21 Board Search Widget
**Author:** wt-search agent

## Problem

The cloglog board now has ~90+ tasks across multiple epics and features. Finding a specific item requires scrolling through the backlog tree or scanning Kanban columns visually. Users often vaguely remember an item exists but don't know which epic/feature it lives under or what status it's in. There's no way to jump directly to an item by partial name.

## Requirements

1. A search input at the top of the board
2. As-you-type results showing matching epics, features, and tasks
3. Results grouped by entity type with entity number prefix (E-1, F-2, T-45)
4. Clicking a result opens it in the existing DetailPanel overlay
5. Keyboard navigation (arrow keys to move, Enter to select, Escape to close)
6. Works across all statuses (backlog, in_progress, review, done, archived)

## Chosen Approach: Server-Side Search Endpoint

Add a `GET /projects/{id}/search?q=term` endpoint that queries PostgreSQL using ILIKE for case-insensitive substring matching across epics, features, and tasks. The frontend calls this endpoint with debouncing and renders the results in a dropdown.

**Why server-side:**
- Can search titles AND descriptions (backlog tree only loads task titles client-side)
- Scales to larger datasets without loading everything into memory
- Clean upgrade path to PostgreSQL full-text search (pg_trgm, tsvector) later
- Proper separation: search is a query concern, belongs in the backend

---

## Backend Design

### Search Endpoint

```
GET /projects/{project_id}/search?q={query}&limit={limit}
```

**Parameters:**
- `q` (required, string, min length 1): Search query
- `limit` (optional, int, default 20, max 50): Maximum results to return

**Response:** `SearchResponse` containing a flat list of `SearchResult` items.

### Response Schema

```python
class SearchResult(BaseModel):
    id: UUID
    type: str          # "epic" | "feature" | "task"
    title: str
    number: int
    status: str        # epic/feature status or task status
    # Breadcrumb context
    epic_title: str | None = None
    epic_color: str | None = None
    feature_title: str | None = None

class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    total: int         # Total matches (before limit)
```

### Repository Method

```python
async def search(
    self, project_id: UUID, query: str, limit: int = 20
) -> tuple[list[dict], int]:
```

The search queries three tables using UNION ALL:

```sql
-- Epics
SELECT id, 'epic' as type, title, number, status,
       NULL as epic_title, NULL as epic_color, NULL as feature_title,
       title as sort_title
FROM epics
WHERE project_id = :project_id
  AND (title ILIKE :pattern OR number::text = :exact_number)

UNION ALL

-- Features (with epic context)
SELECT f.id, 'feature', f.title, f.number, f.status,
       e.title, e.color, NULL,
       f.title
FROM features f
JOIN epics e ON f.epic_id = e.id
WHERE e.project_id = :project_id
  AND (f.title ILIKE :pattern OR f.number::text = :exact_number)

UNION ALL

-- Tasks (with epic + feature context)
SELECT t.id, 'task', t.title, t.number, t.status,
       e.title, e.color, f.title,
       t.title
FROM tasks t
JOIN features f ON t.feature_id = f.id
JOIN epics e ON f.epic_id = e.id
WHERE e.project_id = :project_id
  AND (t.title ILIKE :pattern OR t.number::text = :exact_number)

ORDER BY
  CASE type WHEN 'epic' THEN 1 WHEN 'feature' THEN 2 ELSE 3 END,
  sort_title
LIMIT :limit
```

Where:
- `:pattern` = `%{query}%` (ILIKE for case-insensitive substring match)
- `:exact_number` = extracted number if query matches `/^[EFT]?-?(\d+)$/i`

### Service Method

```python
async def search(
    self, project_id: UUID, query: str, limit: int = 20
) -> SearchResponse:
```

Validates the project exists, delegates to repository, maps results to `SearchResult` objects.

### Route

```python
@router.get("/projects/{project_id}/search", response_model=SearchResponse)
async def search_project(
    project_id: UUID,
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=50),
    service: ServiceDep,
) -> SearchResponse:
```

### Entity Number Matching

When the query matches the pattern `E-5`, `F-21`, `T-89`, or bare `89`:
- Extract the numeric part
- Match against the `number` column in addition to title ILIKE
- Type prefix (E/F/T) filters to that entity type only

---

## Frontend Design

### SearchWidget Component

A controlled text input with a dropdown results list. Placed in `BoardHeader` next to the project title/stats.

```
+----------------------------------------------------------+
|  cloglog    90 tasks · 65 done · 72%    [  Search...  ]  |
+----------------------------------------------------------+
                                           |  Results:     |
                                           |  E-1 Board... |
                                           |  F-21 Board.. |
                                           |  T-89 Write.. |
                                           +---------------+
```

**Props:**
```typescript
interface SearchWidgetProps {
  projectId: string
  onSelect: (type: 'epic' | 'feature' | 'task', id: string) => void
}
```

**Behavior:**
- Empty query: dropdown hidden
- Non-empty query (1+ chars): debounce 200ms, call search API, show results
- Loading state while API call in flight
- Results show: entity number + title + parent context (epic color dot for tasks/features)
- Maximum 20 results displayed
- Clicking a result calls `onSelect` which navigates via URL (same as existing `onItemClick`)
- After selection, clear the search input and close the dropdown

### useSearch Hook

```typescript
// frontend/src/hooks/useSearch.ts
interface SearchResult {
  id: string
  type: 'epic' | 'feature' | 'task'
  title: string
  number: number
  status: string
  epic_title?: string
  epic_color?: string
  feature_title?: string
}

interface UseSearchReturn {
  results: SearchResult[]
  loading: boolean
  search: (query: string) => void
  clear: () => void
}

function useSearch(projectId: string): UseSearchReturn
```

**Implementation:**
1. Maintains `query`, `results`, and `loading` state
2. Debounces API calls by 200ms using `setTimeout` / `clearTimeout`
3. Calls `api.search(projectId, query)` on debounced query changes
4. Aborts in-flight requests when a new query arrives (AbortController)
5. Returns empty results for empty query without calling API

### API Client Addition

```typescript
// In frontend/src/api/client.ts
search: (projectId: string, q: string, limit?: number) =>
  fetchJSON<SearchResponse>(`/projects/${projectId}/search?q=${encodeURIComponent(q)}&limit=${limit ?? 20}`),
```

### Keyboard Navigation

- **Arrow Down / Arrow Up**: Move highlight through results
- **Enter**: Select highlighted result (opens DetailPanel)
- **Escape**: Clear search and close dropdown
- **Cmd/Ctrl+K**: Global shortcut to focus the search input (common pattern)

Implementation:
- Global `keydown` listener on `document` for `Cmd+K` / `Ctrl+K`
- Local `keydown` handler on the search input for arrow keys, Enter, Escape
- `selectedIndex` wraps around (last → first, first → last)
- Results list scrolls to keep highlighted item visible (`scrollIntoView`)

### Styling

Follows existing cloglog design system — no external UI library:

- Input: `var(--bg-tertiary)` background, `var(--border-subtle)` border, `var(--font-body)` font
- Input expands from 240px to 320px on focus (CSS transition)
- Dropdown: `var(--bg-secondary)` background, positioned absolutely below input, max-height 400px
- Results: entity number in `var(--font-mono)`, title in `var(--font-body)`
- Highlighted result: `var(--bg-tertiary)` background
- Entity type indicators: colored dot using epic color
- Status badge on task results (same status color classes)
- Loading spinner while fetching
- Shortcut hint: `Cmd+K` / `Ctrl+K` shown as subtle badge when input is empty

### File Structure

```
# Backend
src/board/
  repository.py    # Add search() method
  services.py      # Add search() method
  routes.py        # Add search endpoint
  schemas.py       # Add SearchResult, SearchResponse

# Frontend
frontend/src/
  api/
    client.ts          # Add search() method
    types.ts           # Add SearchResult, SearchResponse types (or generated-types.ts)
  components/
    SearchWidget.tsx    # Component
    SearchWidget.css    # Styles
    SearchWidget.test.tsx  # Component tests
  hooks/
    useSearch.ts        # Search API hook with debouncing
    useSearch.test.ts   # Hook unit tests
```

---

## Integration

### BoardHeader Changes

Add `SearchWidget` to `BoardHeader`. Now needs `projectId` and `onItemClick` instead of raw data:

```typescript
// Board.tsx passes projectId and callback to BoardHeader
<BoardHeader board={board} projectId={projectId} onItemClick={onItemClick} />

// BoardHeader.tsx renders SearchWidget
<SearchWidget projectId={projectId} onSelect={onItemClick} />
```

### Board.tsx Changes

Thread `projectId` through to `BoardHeader`. The `Board` component already receives backlog and board but now also needs the project ID for the search API call.

### App.tsx Changes

Pass `projectId` to `Board` (it's already available from `useParams`).

---

## Testing Plan

### Backend Unit Tests

1. **Repository: search returns matching epics by title** — ILIKE substring match
2. **Repository: search returns matching features with epic context**
3. **Repository: search returns matching tasks with epic + feature context**
4. **Repository: case-insensitive matching** — "board" matches "Board Redesign"
5. **Repository: entity number matching** — "T-89" matches task 89, "89" matches all types
6. **Repository: type-prefixed number** — "E-1" only matches epics, "F-21" only features
7. **Repository: results limited** — respects limit parameter
8. **Repository: empty query handled** — returns empty or raises validation error
9. **Route: returns 200 with search results**
10. **Route: returns 404 for invalid project**
11. **Route: validates q parameter (min length 1)**
12. **Route: validates limit parameter (1-50 range)**

### Frontend Unit Tests (useSearch.test.ts)

1. **Empty query returns empty results without API call**
2. **Debounces API calls** — rapid typing only triggers one call
3. **Aborts in-flight requests** — new query cancels previous
4. **Maps API response to SearchResult[]**
5. **Loading state tracks API call lifecycle**
6. **Clear resets results and query**

### Frontend Component Tests (SearchWidget.test.tsx)

1. **Renders search input** — input visible with placeholder
2. **Empty query shows no results** — dropdown hidden when input empty
3. **Typing shows filtered results** — enter text, verify results appear after debounce
4. **Clicking result calls onSelect** — verify callback with correct type and id
5. **Keyboard navigation** — arrow keys move highlight, Enter selects, Escape closes
6. **Cmd+K focuses input** — global keyboard shortcut works
7. **Clearing input hides dropdown** — backspace to empty closes results
8. **Loading state shown** — spinner visible during API call

### Integration Tests (Backend)

- End-to-end: create project with epics/features/tasks, search by title, verify results
- Verify search results contain correct breadcrumb context

---

## Scope & Non-Goals

**In scope:**
- Server-side search endpoint with ILIKE matching
- Search by title substring
- Search by entity number (E-1, F-21, T-89, or just the number)
- Frontend search widget with debounced API calls
- Keyboard navigation (arrows, Enter, Escape, Cmd+K)
- Breadcrumb context in results (epic color, feature title)

**Not in scope (future):**
- Full-text search with PostgreSQL tsvector/pg_trgm
- Fuzzy matching / typo tolerance
- Search history / recent searches
- Filter by status, priority, or epic
- Description search (easy to add to the ILIKE query later)

## Risks

1. **Latency** — ILIKE on ~100 rows is sub-millisecond. No concern at current scale. If dataset grows, add a GIN index with pg_trgm.
2. **Debounce UX** — 200ms debounce balances responsiveness vs API call volume. Can tune if needed.
3. **Request cancellation** — AbortController handles stale responses. Standard pattern.
