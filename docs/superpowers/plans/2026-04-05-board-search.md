# F-21: Board Search Widget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a search widget to the board header that queries a server-side search endpoint and shows matching epics, features, and tasks as-you-type. Clicking a result opens it in the existing DetailPanel overlay.

**Architecture:** Backend UNION ALL query across epics/features/tasks with ILIKE matching, exposed as `GET /projects/{id}/search`. Frontend `SearchWidget` component with debounced API calls, keyboard navigation, and `Cmd+K` shortcut.

**Tech Stack:** Python/FastAPI + SQLAlchemy (backend endpoint), TypeScript/React (frontend component + hook), Vitest + @testing-library/react (frontend tests), pytest (backend tests)

**Design Spec:** `docs/superpowers/specs/2026-04-05-board-search-design.md`

---

### Task 1: Add search schemas and repository method

**Files:**
- Modify: `src/board/schemas.py`
- Modify: `src/board/repository.py`

- [ ] **Step 1: Add SearchResult and SearchResponse schemas**

In `src/board/schemas.py`, add after the `BacklogEpic` class (line ~178):

```python
# --- Search ---


class SearchResult(BaseModel):
    id: UUID
    type: str  # "epic" | "feature" | "task"
    title: str
    number: int
    status: str
    epic_title: str | None = None
    epic_color: str | None = None
    feature_title: str | None = None


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    total: int
```

- [ ] **Step 2: Add search repository method**

In `src/board/repository.py`, add a `search` method to `BoardRepository`:

```python
import re
from sqlalchemy import literal_column, text, union_all

async def search(
    self, project_id: UUID, query: str, limit: int = 20
) -> tuple[list[dict], int]:
```

Implementation:
1. Parse the query for entity number patterns: regex `/^[EFT]?-?(\d+)$/i`
2. If the query matches a type prefix (E/F/T), filter to that entity type only
3. Build three SELECT statements (epics, features with epic join, tasks with epic+feature join)
4. Each SELECT uses `ILIKE '%{query}%'` on title OR `number::text = :exact_number`
5. UNION ALL the three queries, ORDER BY type priority (epic=1, feature=2, task=3) then title
6. Execute with LIMIT, also run a COUNT query for total
7. Return `(list[dict], total_count)`

Use `text()` for the raw SQL UNION query since SQLAlchemy ORM doesn't cleanly express cross-table unions with different column shapes. Parameterize all user input to prevent SQL injection.

- [ ] **Step 3: Run existing tests to verify nothing broke**

```bash
make test-board
```

- [ ] **Step 4: Commit**

```bash
git add src/board/schemas.py src/board/repository.py
git commit -m "feat(search): add SearchResult/SearchResponse schemas and repository search method"
```

---

### Task 2: Add search service method and route

**Files:**
- Modify: `src/board/services.py`
- Modify: `src/board/routes.py`

- [ ] **Step 1: Add search service method**

In `src/board/services.py`, add to `BoardService`:

```python
async def search(
    self, project_id: UUID, query: str, limit: int = 20
) -> SearchResponse:
    project = await self._repo.get_project(project_id)
    if not project:
        raise ValueError("Project not found")
    results, total = await self._repo.search(project_id, query, limit)
    return SearchResponse(
        query=query,
        results=[SearchResult(**r) for r in results],
        total=total,
    )
```

- [ ] **Step 2: Add search route**

In `src/board/routes.py`, add the search endpoint. Import `Query` from FastAPI:

```python
from fastapi import Query as QueryParam

@router.get("/projects/{project_id}/search", response_model=SearchResponse)
async def search_project(
    project_id: UUID,
    q: str = QueryParam(..., min_length=1),
    limit: int = QueryParam(20, ge=1, le=50),
    service: ServiceDep = Depends(),
) -> SearchResponse:
    try:
        return await service.search(project_id, q, limit)
    except ValueError:
        raise HTTPException(status_code=404, detail="Project not found")
```

Add the necessary schema imports to the routes file.

- [ ] **Step 3: Run tests**

```bash
make test-board
```

- [ ] **Step 4: Commit**

```bash
git add src/board/services.py src/board/routes.py
git commit -m "feat(search): add search service method and GET /projects/{id}/search endpoint"
```

---

### Task 3: Add backend tests for search

**Files:**
- Modify: `tests/board/test_routes.py`

- [ ] **Step 1: Add search endpoint integration tests**

Add tests to `tests/board/test_routes.py` following the existing pattern (create project → create epic → create feature → create task → test search):

1. `test_search_returns_matching_tasks_by_title` — create items, search by substring, verify results
2. `test_search_returns_matching_epics_and_features` — verify all entity types returned
3. `test_search_case_insensitive` — "board" matches "Board Redesign"
4. `test_search_by_entity_number` — "T-1" matches task number 1
5. `test_search_by_bare_number` — "1" matches all entity types with number 1
6. `test_search_type_prefix_filters` — "E-1" only matches epics, "F-1" only features
7. `test_search_respects_limit` — create many items, verify limit works
8. `test_search_empty_query_rejected` — `q=""` returns 422
9. `test_search_invalid_project_returns_404`
10. `test_search_includes_breadcrumb_context` — tasks have epic_title, epic_color, feature_title

Each test should follow the existing pattern: async function, `client` fixture, chain POST calls to create test data, then GET search endpoint and assert.

- [ ] **Step 2: Run all tests**

```bash
make test-board
```

- [ ] **Step 3: Commit**

```bash
git add tests/board/test_routes.py
git commit -m "test(search): add integration tests for search endpoint"
```

---

### Task 4: Add frontend search API client and types

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Add SearchResult and SearchResponse types**

In `frontend/src/api/types.ts`, add after the `AppNotification` interface (line ~45):

```typescript
// Search (not yet in OpenAPI contract)
export interface SearchResult {
  id: string
  type: 'epic' | 'feature' | 'task'
  title: string
  number: number
  status: string
  epic_title?: string
  epic_color?: string
  feature_title?: string
}

export interface SearchResponse {
  query: string
  results: SearchResult[]
  total: number
}
```

- [ ] **Step 2: Add search method to API client**

In `frontend/src/api/client.ts`, add to the `api` object (before the SSE stream URL):

```typescript
// Search
search: (projectId: string, q: string, limit?: number, signal?: AbortSignal) =>
  fetchJSON<SearchResponse>(
    `/projects/${projectId}/search?q=${encodeURIComponent(q)}&limit=${limit ?? 20}`,
    { signal },
  ),
```

Update the import line to include `SearchResponse`.

- [ ] **Step 3: Commit**

```bash
cd frontend && git add src/api/types.ts src/api/client.ts
git commit -m "feat(search): add search types and API client method"
```

---

### Task 5: Create useSearch hook with debouncing

**Files:**
- Create: `frontend/src/hooks/useSearch.ts`
- Create: `frontend/src/hooks/useSearch.test.ts`

- [ ] **Step 1: Create useSearch hook**

Create `frontend/src/hooks/useSearch.ts`:

```typescript
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { SearchResult } from '../api/types'

interface UseSearchReturn {
  results: SearchResult[]
  loading: boolean
  search: (query: string) => void
  clear: () => void
}

export function useSearch(projectId: string): UseSearchReturn {
  const [results, setResults] = useState<SearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clear = useCallback(() => {
    setResults([])
    setLoading(false)
    if (timerRef.current) clearTimeout(timerRef.current)
    if (abortRef.current) abortRef.current.abort()
  }, [])

  const search = useCallback((query: string) => {
    if (!query.trim()) {
      clear()
      return
    }

    setLoading(true)
    if (timerRef.current) clearTimeout(timerRef.current)
    if (abortRef.current) abortRef.current.abort()

    timerRef.current = setTimeout(async () => {
      const controller = new AbortController()
      abortRef.current = controller
      try {
        const res = await api.search(projectId, query, 20, controller.signal)
        if (!controller.signal.aborted) {
          setResults(res.results)
          setLoading(false)
        }
      } catch {
        if (!controller.signal.aborted) {
          setResults([])
          setLoading(false)
        }
      }
    }, 200)
  }, [projectId, clear])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
      if (abortRef.current) abortRef.current.abort()
    }
  }, [])

  return { results, loading, search, clear }
}
```

- [ ] **Step 2: Create useSearch tests**

Create `frontend/src/hooks/useSearch.test.ts`:

Test cases (using `vi.mock` for `../api/client` and `vi.useFakeTimers`):
1. `empty query returns empty results without API call`
2. `debounces API calls` — call search rapidly, advance timers, verify single API call
3. `aborts in-flight requests on new query` — verify AbortController usage
4. `maps API response to results`
5. `loading state tracks API call lifecycle`
6. `clear resets results`

Use `renderHook` from `@testing-library/react` and `act` for state updates.

- [ ] **Step 3: Run tests**

```bash
cd frontend && npx vitest run src/hooks/useSearch.test.ts
```

- [ ] **Step 4: Commit**

```bash
cd frontend && git add src/hooks/useSearch.ts src/hooks/useSearch.test.ts
git commit -m "feat(search): add useSearch hook with debouncing and AbortController"
```

---

### Task 6: Create SearchWidget component

**Files:**
- Create: `frontend/src/components/SearchWidget.tsx`
- Create: `frontend/src/components/SearchWidget.css`
- Create: `frontend/src/components/SearchWidget.test.tsx`

- [ ] **Step 1: Create SearchWidget component**

Create `frontend/src/components/SearchWidget.tsx`:

```typescript
interface SearchWidgetProps {
  projectId: string
  onSelect: (type: 'epic' | 'feature' | 'task', id: string) => void
}
```

Implementation:
1. Uses `useSearch(projectId)` hook
2. Controlled input with `onChange` calling `search(value)`
3. Dropdown absolutely positioned below input, shown when `results.length > 0` or loading
4. Each result row: colored dot (epic_color), entity prefix (E-/F-/T-), number, title
5. Breadcrumb context: feature_title for tasks, epic_title for features
6. Keyboard navigation state: `selectedIndex` managed via `onKeyDown`
7. Arrow Up/Down moves index (wraps), Enter selects, Escape clears
8. Global `Cmd+K` / `Ctrl+K` listener to focus input (via `useEffect` on `document`)
9. Click outside closes dropdown (via `useRef` + `mousedown` listener)
10. On select: call `onSelect(result.type, result.id)`, clear input and results

- [ ] **Step 2: Create SearchWidget styles**

Create `frontend/src/components/SearchWidget.css`:

Follow existing cloglog design system variables:
- Input: `var(--bg-tertiary)` background, `var(--border-subtle)` border, `var(--font-body)` font
- Input width: 240px default → 320px on focus (CSS transition)
- Dropdown: `var(--bg-secondary)` background, absolute positioning, max-height 400px, overflow-y auto
- Result row: padding 8px 12px, cursor pointer
- Highlighted row: `var(--bg-tertiary)` background
- Entity number: `var(--font-mono)`, muted color
- Epic color dot: 8px circle, inline-block
- Loading spinner: small animated spinner
- `Cmd+K` hint: subtle badge in input when empty

- [ ] **Step 3: Create SearchWidget tests**

Create `frontend/src/components/SearchWidget.test.tsx`:

Test cases:
1. `renders search input with placeholder` — verify input element exists
2. `empty query shows no dropdown` — type nothing, no results container
3. `typing shows results after debounce` — type text, advance timers, verify results render
4. `clicking result calls onSelect with correct type and id` — click a result row
5. `keyboard navigation: arrow keys move highlight` — press Down, verify highlight changes
6. `keyboard navigation: Enter selects highlighted` — press Enter, verify onSelect called
7. `keyboard navigation: Escape clears` — press Escape, verify input cleared
8. `Cmd+K focuses input` — dispatch keyboard event, verify input focused
9. `loading state shows spinner` — mock slow API, verify spinner visible

Mock `useSearch` hook to control results and loading state.

- [ ] **Step 4: Run tests**

```bash
cd frontend && npx vitest run src/components/SearchWidget.test.tsx
```

- [ ] **Step 5: Commit**

```bash
cd frontend && git add src/components/SearchWidget.tsx src/components/SearchWidget.css src/components/SearchWidget.test.tsx
git commit -m "feat(search): add SearchWidget component with keyboard navigation"
```

---

### Task 7: Integrate SearchWidget into Board

**Files:**
- Modify: `frontend/src/components/Board.tsx`
- Modify: `frontend/src/components/BoardHeader.tsx`
- Modify: `frontend/src/components/Board.test.tsx`

- [ ] **Step 1: Update BoardHeader to accept and render SearchWidget**

In `frontend/src/components/BoardHeader.tsx`:

1. Add props: `projectId: string`, `onItemClick: (type, id) => void`
2. Import and render `SearchWidget` with those props
3. Place in the header flex container, after the stats span

```typescript
interface BoardHeaderProps {
  board: BoardResponse
  projectId: string
  onItemClick: (type: 'epic' | 'feature' | 'task', id: string) => void
}
```

Add `SearchWidget` to the flex row with `margin-left: auto` to push it right.

- [ ] **Step 2: Update Board to pass projectId and onItemClick to BoardHeader**

In `frontend/src/components/Board.tsx`:

1. Add `projectId: string` to `BoardProps`
2. Pass `projectId` and `onItemClick` to `BoardHeader`

```typescript
<BoardHeader board={board} projectId={projectId} onItemClick={onItemClick} />
```

- [ ] **Step 3: Update App.tsx to pass projectId to Board**

In `frontend/src/App.tsx`, the `Board` component call needs `projectId` prop:

```typescript
<Board
  board={board}
  backlog={backlog}
  projectId={selectedProjectId}
  onTaskClick={handleTaskClick}
  onItemClick={openDetail}
  onRefresh={refetch}
/>
```

Note: `selectedProjectId` is already available in App.tsx.

- [ ] **Step 4: Update Board tests**

In `frontend/src/components/Board.test.tsx`:
- Add `projectId` prop to all Board renders
- Add test: `renders search widget in header`

- [ ] **Step 5: Run full frontend tests**

```bash
cd frontend && make test
```

- [ ] **Step 6: Run full quality gate**

```bash
make quality
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/Board.tsx frontend/src/components/BoardHeader.tsx frontend/src/App.tsx frontend/src/components/Board.test.tsx
git commit -m "feat(search): integrate SearchWidget into BoardHeader"
```

---

## Task Dependencies

```
Task 1 (schemas + repo) → Task 2 (service + route) → Task 3 (backend tests)
Task 4 (frontend types) → Task 5 (useSearch hook) → Task 6 (SearchWidget) → Task 7 (integration)
Task 1-3 (backend) and Task 4-6 (frontend) can run in parallel.
Task 7 depends on both Task 3 and Task 6.
```

## Parallelization Strategy

Two subagents can work concurrently:
- **Backend subagent:** Tasks 1, 2, 3 (sequentially)
- **Frontend subagent:** Tasks 4, 5, 6 (sequentially)
- **Integration:** Task 7 runs after both complete (either subagent or main agent)

## Risk Mitigations

1. **SQL injection** — All user input parameterized via SQLAlchemy `text()` bind params. Never interpolate query strings.
2. **Stale responses** — AbortController cancels in-flight requests when query changes.
3. **Worktree discipline** — All changes are in `src/board/` (backend) and `frontend/src/` (frontend), both within wt-search's assigned directories.
4. **Test baseline** — Run `make test-board` and `cd frontend && make test` before writing any code to establish green baseline.
