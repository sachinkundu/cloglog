# Demo: T-127 — assign_task MCP tool

## What was built

A new `assign_task` endpoint and MCP tool that lets the master agent assign tasks to running worktree agents without changing the task's status.

### Backend: `PATCH /agents/{worktree_id}/assign-task`

Sets `worktree_id` on the task so it appears in `get_my_tasks`. Does not change status to `in_progress` — the agent picks it up and starts it when ready. Also queues a notification message delivered on the next heartbeat.

### MCP tool: `assign_task`

Wraps the backend endpoint. Parameters: `worktree_id` (target agent), `task_id` (task to assign).

## Test results

### Backend (56 passed, 4 new)

New tests in `tests/agent/test_integration.py`:
- `test_assign_task_sets_worktree_id` — verifies task appears in get_my_tasks after assignment
- `test_assign_task_sends_notification_message` — verifies heartbeat delivers notification
- `test_assign_task_unknown_worktree` — 404 for nonexistent worktree
- `test_assign_task_unknown_task` — 404 for nonexistent task

### MCP server (25 passed, 1 new)

- `assign_task calls PATCH /agents/{wt}/assign-task` — verifies correct HTTP method and path

## Verification

```
make quality — PASSED
make test-agent — 56 passed
cd mcp-server && make test — 25 passed
```
