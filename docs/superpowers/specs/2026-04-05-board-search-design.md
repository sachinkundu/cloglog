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

## Approach Evaluation

### Option A: Client-side filtering of existing data

Filter the backlog tree + board columns data already loaded in the frontend.

**Pros:**
- Zero backend changes — no API contract modification, no migration
- Instant results (no network latency)
- Data is already loaded by `useBoard` hook (backlog + board columns)
- Simplest to implement and test

**Cons:**
- Only searches data currently in memory (backlog tree has all hierarchy; board columns have all non-backlog tasks)
- Can't search task descriptions without loading them (backlog tasks only have title, status, priority, number)
- Won't scale if the project grows to thousands of tasks (unlikely for cloglog's use case)

### Option B: Server-side search endpoint

Add a `GET /projects/{id}/search?q=term` endpoint with SQL ILIKE queries.

**Pros:**
- Can search descriptions, notes, and other fields not loaded client-side
- Scales to larger datasets
- Could add full-text search (pg_trgm) later

**Cons:**
- Requires API contract change (new endpoint, new response schema)
- Requires DDD architect/reviewer cycle for the contract
- Network latency on each keystroke (needs debouncing)
- More complex implementation (backend + frontend)

### Option C: Hybrid — client-side now, server-side later

Start with client-side filtering. If search needs grow (description search, fuzzy matching), add a server endpoint later behind the same UI.

**Pros:**
- Ships fast with zero backend changes
- UI component is the same regardless of data source
- Clean upgrade path

**Cons:**
- Slightly more design thought upfront to keep the search hook swappable

## Recommended Approach: Option A (Client-side filtering)

**Rationale:** The backlog tree already contains ALL epics, features, and tasks (including done/archived). The board columns contain all non-backlog tasks with full details. Between these two data sources, every entity is available client-side. The dataset is small (~100 items) and will stay small for this project. Client-side search gives instant results with zero backend work.

The search component will be designed with a clean data interface so it could be backed by a server endpoint later without UI changes.

## Component Design

### SearchWidget component

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
  backlog: BacklogEpic[]
  board: BoardResponse
  onSelect: (type: 'epic' | 'feature' | 'task', id: string) => void
}
```

**Behavior:**
- Empty query: dropdown hidden
- Non-empty query (1+ chars): show matching results, grouped by type
- Case-insensitive substring match on title
- Entity number match: typing "T-89" or "89" matches task number 89
- Results show: entity number + title + parent context (epic color dot for tasks/features)
- Maximum 20 results displayed (to avoid overwhelming the dropdown)
- Clicking a result calls `onSelect` which navigates via URL (same as existing `onItemClick`)
- After selection, clear the search input and close the dropdown

### Search algorithm

Simple substring + number matching, no external library needed:

```typescript
function searchEntities(
  backlog: BacklogEpic[],
  board: BoardResponse,
  query: string
): SearchResult[] {
  const q = query.toLowerCase().trim()
  if (!q) return []

  const results: SearchResult[] = []
  const numberMatch = q.match(/^[eft]-?(\d+)$/i) || q.match(/^(\d+)$/)
  const targetNumber = numberMatch ? parseInt(numberMatch[1]) : null

  for (const { epic, features } of backlog) {
    // Match epics
    if (matchesQuery(epic.title, q, 'epic', epic.number, targetNumber)) {
      results.push({ type: 'epic', id: epic.id, title: epic.title,
        number: epic.number, color: epic.color })
    }
    // Match features
    for (const { feature, tasks } of features) {
      if (matchesQuery(feature.title, q, 'feature', feature.number, targetNumber)) {
        results.push({ type: 'feature', id: feature.id, title: feature.title,
          number: feature.number, epicColor: epic.color, epicTitle: epic.title })
      }
      // Match tasks
      for (const task of tasks) {
        if (matchesQuery(task.title, q, 'task', task.number, targetNumber)) {
          results.push({ type: 'task', id: task.id, title: task.title,
            number: task.number, epicColor: epic.color,
            featureTitle: feature.title, status: task.status })
        }
      }
    }
  }
  return results.slice(0, 20)
}
```

### Keyboard navigation

- **Arrow Down / Arrow Up**: Move highlight through results
- **Enter**: Select highlighted result (opens DetailPanel)
- **Escape**: Clear search and close dropdown
- **Cmd/Ctrl+K**: Global shortcut to focus the search input (common pattern)

### Styling

Follows existing cloglog design system — no external UI library:

- Input: `var(--bg-tertiary)` background, `var(--border-subtle)` border, `var(--font-body)` font
- Dropdown: `var(--bg-secondary)` background, positioned absolutely below input
- Results: entity number in `var(--font-mono)`, title in `var(--font-body)`
- Highlighted result: `var(--bg-tertiary)` background
- Entity type indicators: colored dot using epic color
- Status badge on task results (same `.status-{status}` classes)

### useSearch hook

Extract the search logic into a reusable hook for testability and separation of concerns:

```typescript
// frontend/src/hooks/useSearch.ts
interface SearchResult {
  id: string
  type: 'epic' | 'feature' | 'task'
  title: string
  number: number
  epicColor?: string
  epicTitle?: string
  featureTitle?: string
  status?: string
}

function useSearch(
  backlog: BacklogEpic[],
  board: BoardResponse | null,
): {
  search: (query: string) => SearchResult[]
}
```

The hook uses `useMemo` to flatten backlog and board data into a searchable list, deduplicating tasks that appear in both. The `search` function returns results sorted by relevance: prefix matches first, then substring matches, ordered by type (epics > features > tasks).

### File structure

```
frontend/src/
  components/
    SearchWidget.tsx       # Component
    SearchWidget.css       # Styles
    SearchWidget.test.tsx  # Component tests
  hooks/
    useSearch.ts           # Search logic hook
    useSearch.test.ts      # Hook unit tests
```

## Integration

### BoardHeader changes

Add `SearchWidget` to `BoardHeader`. Pass `backlog` and `board` as props (requires threading them through from `Board`).

```typescript
// Board.tsx passes data to BoardHeader
<BoardHeader board={board} backlog={backlog} onItemClick={onItemClick} />

// BoardHeader.tsx renders SearchWidget
<SearchWidget backlog={backlog} board={board} onSelect={onItemClick} />
```

### App.tsx changes

None needed. The existing `openDetail` callback already handles navigation for all entity types.

## Testing Plan

### Unit tests (useSearch.test.ts)

1. **Empty query returns empty results**
2. **Single character query filters correctly**
3. **Case-insensitive matching** — "board" matches "Board Search Widget"
4. **Entity number matching** — "T-89" matches task 89; bare "89" also matches
5. **Prefix matches rank before substring matches**
6. **Results deduplicated** — task in both backlog and board appears once
7. **Max 20 results enforced**
8. **Breadcrumb context populated** — epic color, feature title on task results
9. **All entity types searchable** — epics, features, and tasks appear

### Component tests (SearchWidget.test.tsx)

1. **Renders search input** — input visible with placeholder
2. **Empty query shows no results** — dropdown hidden when input empty
3. **Typing shows filtered results** — enter text, verify results appear
4. **Clicking result calls onSelect** — verify callback with correct type and id
5. **Keyboard navigation** — arrow keys move highlight, Enter selects, Escape closes
6. **Cmd+K focuses input** — global keyboard shortcut works
7. **Clearing input hides dropdown** — backspace to empty closes results
8. **Results update when data changes** — simulate SSE update via prop change

### Integration tests

- Verify SearchWidget renders in BoardHeader within the full Board component
- Verify clicking a search result opens the DetailPanel (via existing routing)

## Scope & Non-Goals

**In scope:**
- Search by title substring
- Search by entity number (E-1, F-21, T-89, or just the number)
- Keyboard navigation
- Global Cmd+K shortcut

**Not in scope (future):**
- Description search (would need server-side endpoint)
- Fuzzy matching / typo tolerance
- Search history / recent searches
- Filter by status, priority, or epic
- Full-text search with ranking

## Risks

1. **Backlog data completeness** — The backlog tree contains all entities. Board columns duplicate tasks with extra fields (description). For search-by-title, backlog data is sufficient. No risk here.
2. **Performance** — ~100 entities, simple string matching. No performance concern. If it ever grows, we add debouncing or switch to server-side.
3. **Stale data** — SSE events update the board/backlog in real-time. Search operates on current state. No staleness risk.
