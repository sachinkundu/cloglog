# F-5: SSE Event Pipeline — Complete Coverage

**Date:** 2026-04-05
**Feature:** F-5 SSE Event Pipeline (Epic: Live Dashboard)
**Scope:** T-18 (document_attached), T-79 (CRUD events for all board entities)

## Problem

Creating, deleting, or attaching documents to epics, features, and tasks does not emit SSE events. The dashboard only updates on page refresh. The user expects live updates when agents (or the master agent) create entities via the MCP tools.

Currently, only `task_status_changed`, `worktree_online`, and `worktree_offline` events are emitted and handled.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Frontend update strategy | Full refetch on any new event | Board payload is small (~62 tasks). Granular client-side updates add complexity not justified at this scale. Existing granular handler for `task_status_changed` stays. |
| Event emission location | Route handlers (not services) | DDD boundary respect. Services stay within their bounded context. Routes orchestrate cross-cutting concerns like event publishing. Follows existing pattern in `board/routes.py`. |
| Event granularity | Fine-grained types per operation | Explicit, debuggable, future-proof for selective handling later. Cost is trivial (enum values). |
| Scope | Only existing API endpoints | YAGNI. No speculative events for endpoints that don't exist yet. |

## New Event Types

Added to `EventType` enum in `src/shared/events.py`:

```python
EPIC_CREATED = "epic_created"
EPIC_DELETED = "epic_deleted"
FEATURE_CREATED = "feature_created"
FEATURE_DELETED = "feature_deleted"
TASK_CREATED = "task_created"
TASK_DELETED = "task_deleted"
TASK_NOTE_ADDED = "task_note_added"
BULK_IMPORT = "bulk_import"
# DOCUMENT_ATTACHED already exists, just not emitted
```

Each event carries `project_id` (for SSE routing) and minimal identifying data for debugging:
- `epic_created`: `{"epic_id": "...", "title": "..."}`
- `task_deleted`: `{"task_id": "..."}`
- `document_attached`: `{"document_id": "...", "attached_to_type": "...", "attached_to_id": "..."}`
- `bulk_import`: `{"epics_created": N, "features_created": N, "tasks_created": N}`

## Backend: Event Emission Points

All in route handlers. The `project_id` resolution per route:

| Route | File | project_id source |
|-------|------|------------------|
| `POST /projects/{id}/epics` | `board/routes.py` | path param |
| `DELETE /epics/{id}` | `board/routes.py` | `epic.project_id` (load before delete) |
| `POST /epics/{id}/features` | `board/routes.py` | load epic → `epic.project_id` |
| `DELETE /features/{id}` | `board/routes.py` | load feature → load epic → `epic.project_id` |
| `POST /features/{id}/tasks` | `board/routes.py` | load feature → load epic → `epic.project_id` |
| `DELETE /tasks/{id}` | `board/routes.py` | load task → feature → epic → `epic.project_id` |
| `POST /documents` | `document/routes.py` | resolve from `attached_to_type` + `attached_to_id` |
| `POST /projects/{id}/import` | `board/routes.py` | path param |
| `POST /agents/{wt}/task-note` | `agent/routes.py` | load task → feature → epic → `epic.project_id` |

**Delete endpoints** must capture `project_id` before deleting the entity.

**Document route** needs a helper to resolve `project_id` from the attached entity. This helper walks up the chain based on `attached_to_type`:
- `task` → feature → epic → project
- `feature` → epic → project
- `epic` → project

The helper lives in the document route file (not in a service) and takes a `BoardRepository` to do the lookups. This is the gateway/routes layer orchestrating, not a context boundary violation.

## Frontend Changes

**`src/hooks/useSSE.ts`** — Add new event type strings to the `eventTypes` array:

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

**`src/hooks/useBoard.ts`** — No changes needed. The existing `else` fallback at line 86 already calls `fetchBoard()` for any event type that isn't `task_status_changed` or `worktree_online/offline`. The new events will be caught by this fallback.

**`src/api/types.ts`** — Update the `SSEEvent` type to include new event types in the union.

## Testing Strategy

**Backend (existing test files):**
- For each route that now emits an event, assert that `event_bus.publish` was called with the correct `EventType`, `project_id`, and entity data
- One test for the document route's project_id resolution helper (the most complex path: task → feature → epic → project)
- Add event assertions to the existing e2e full workflow test

**Frontend (existing test files):**
- Verify new event types are in the `useSSE.ts` listener array
- The `useBoard.ts` refetch-on-unknown-event path is already tested

No new test files. All additions go in existing test files.

## Files Changed

| File | Change |
|------|--------|
| `src/shared/events.py` | Add 8 new EventType enum values |
| `src/board/routes.py` | Emit events in create epic, delete epic, create feature, delete feature, create task, delete task, import routes |
| `src/document/routes.py` | Add project_id resolver helper, emit `DOCUMENT_ATTACHED` |
| `src/agent/routes.py` | Emit `TASK_NOTE_ADDED` in task-note endpoint |
| `frontend/src/hooks/useSSE.ts` | Add new event types to listener array |
| `frontend/src/api/types.ts` | Update SSEEvent type union |
| `tests/board/test_routes.py` | Add event emission assertions |
| `tests/document/test_routes.py` | Add document_attached event test |
| `tests/agent/test_integration.py` | Add task_note_added event test |
| `tests/e2e/test_full_workflow.py` | Add event assertions to workflow |
