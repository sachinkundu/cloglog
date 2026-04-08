# Demo: T-127 — assign_task endpoint and MCP tool

## New endpoint

**`PATCH /api/v1/agents/{worktree_id}/assign-task`**

Assigns a task to a running agent's worktree without changing the task's status. The agent sees the task on its next `get_my_tasks` call. A notification message is also queued for delivery via heartbeat.

### Request

```bash
curl -X PATCH http://localhost:8000/api/v1/agents/3ab22764-6d87-4123-a7b3-13c7d9470f81/assign-task \
  -H "Content-Type: application/json" \
  -d '{"task_id": "2999a683-ce35-49af-9e9c-6255b6158511"}'
```

### Response (200 OK)

```json
{
  "task_id": "2999a683-ce35-49af-9e9c-6255b6158511",
  "worktree_id": "3ab22764-6d87-4123-a7b3-13c7d9470f81",
  "status": "assigned"
}
```

Note: `status` is always `"assigned"` — this confirms the assignment happened. The task's actual board status (backlog, in_progress, etc.) is **not changed**.

### Error: unknown worktree (404)

```bash
curl -X PATCH http://localhost:8000/api/v1/agents/00000000-0000-0000-0000-000000000000/assign-task \
  -H "Content-Type: application/json" \
  -d '{"task_id": "2999a683-ce35-49af-9e9c-6255b6158511"}'
```

```json
{"detail": "Worktree 00000000-0000-0000-0000-000000000000 not found"}
```

### Error: unknown task (404)

```json
{"detail": "Task 00000000-0000-0000-0000-000000000000 not found"}
```

---

## Notification via heartbeat

After assignment, the target agent receives a message on its next heartbeat:

```bash
curl -X POST http://localhost:8000/api/v1/agents/3ab22764-6d87-4123-a7b3-13c7d9470f81/heartbeat
```

```json
{
  "status": "ok",
  "last_heartbeat": "2026-04-08T11:15:00.000Z",
  "shutdown_requested": false,
  "pending_messages": [
    "[system] New task assigned: T-127 — Add assign_task MCP tool. Call get_my_tasks to see it."
  ]
}
```

---

## Verifying assignment via get_my_tasks

```bash
curl http://localhost:8000/api/v1/agents/3ab22764-6d87-4123-a7b3-13c7d9470f81/tasks
```

```json
[
  {
    "id": "2999a683-ce35-49af-9e9c-6255b6158511",
    "title": "Add assign_task MCP tool",
    "description": "...",
    "status": "backlog",
    "priority": "expedite"
  }
]
```

The task appears in the agent's task list with its **original status** (e.g., `backlog`), not `in_progress`. The agent calls `start_task` when ready to begin.

---

## MCP tool

The `assign_task` MCP tool wraps this endpoint:

| Parameter | Type | Description |
|-----------|------|-------------|
| `worktree_id` | string | UUID of the target agent worktree |
| `task_id` | string | UUID of the task to assign |

---

## Difference from start_task

| | `assign_task` | `start_task` |
|---|---|---|
| Sets worktree_id | Yes | Yes |
| Changes status | No | Yes → `in_progress` |
| Sends notification | Yes | No |
| Use case | Master agent pre-assigns before launch | Agent picks up and begins work |
