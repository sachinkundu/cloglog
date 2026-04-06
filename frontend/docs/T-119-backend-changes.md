# T-119: Block agents from moving tasks to done

This document describes the exact backend changes needed to prevent agents from
marking tasks as "done". Only the user can move tasks to done via the board UI
(drag-and-drop, implemented in PR #51).

## Changes Required

### 1. `src/agent/services.py` — `complete_task()` (line ~149)

Add this guard at the top of the function, before any other validation:

```python
async def complete_task(
    self, worktree_id: UUID, task_id: UUID, pr_url: str | None = None
) -> dict[str, object]:
    raise HTTPException(
        status_code=409,
        detail="Agents cannot mark tasks as done. Move to review and wait for the user.",
    )
```

Or if you want to keep the function signature but just block the action, add
the raise as the first line of the function body.

### 2. `src/agent/services.py` — `update_task_status()` (line ~226)

Add a guard after worktree/task validation, before the existing status checks:

```python
if status == "done":
    raise HTTPException(
        status_code=409,
        detail="Agents cannot mark tasks as done. Move to review and wait for the user.",
    )
```

Insert this around line 225, after the task existence check but before the
review/pr_url guards.

### 3. `mcp-server/src/tools.ts` — Tool descriptions

Update the `complete_task` tool description to note:
> "DEPRECATED: Agents cannot mark tasks as done. Move tasks to review instead."

Update the `update_task_status` tool description to note:
> "Move task to a specific column. Note: agents cannot set status to 'done' — only the user can do this via the board UI."

### 4. `src/board/routes.py` — NO CHANGES

The board PATCH route (`PATCH /tasks/{task_id}`) stays unrestricted. This is
the user's route for drag-and-drop status changes.

## Testing

Add tests in `tests/agent/`:

```python
async def test_complete_task_blocked(agent_service, worktree, task):
    """Agents cannot mark tasks as done."""
    with pytest.raises(HTTPException) as exc:
        await agent_service.complete_task(worktree.id, task.id)
    assert exc.value.status_code == 409
    assert "cannot mark tasks as done" in exc.value.detail.lower()

async def test_update_task_status_done_blocked(agent_service, worktree, task):
    """Agents cannot set status to done."""
    with pytest.raises(HTTPException) as exc:
        await agent_service.update_task_status(worktree.id, task.id, "done")
    assert exc.value.status_code == 409

async def test_update_task_status_review_allowed(agent_service, worktree, task):
    """Agents can still move tasks to review."""
    # Should not raise
    await agent_service.update_task_status(worktree.id, task.id, "review", pr_url="https://github.com/...")
```
