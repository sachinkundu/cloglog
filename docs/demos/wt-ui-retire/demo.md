# T-148: Retire Archived Tasks

Permanently retire archived/done tasks from the board. Retired tasks are
excluded from board and backlog views but remain searchable.

## Retire endpoints exist

```bash
grep -n "def retire" src/board/routes.py
```

```output
353:async def retire_task(task_id: UUID, service: ServiceDep) -> TaskResponse:
380:async def retire_all_done(project_id: UUID, service: ServiceDep) -> dict[str, int]:
```

## Task model has retired field

```bash
grep "retired" src/board/models.py
```

```output
    retired: Mapped[bool] = mapped_column(default=False)
```

## Board query filters retired tasks

```bash
grep -c "Task.retired" src/board/repository.py
```

```output
3
```

## Frontend retire API methods

```bash
grep "retireTask\|retireDone" frontend/src/api/client.ts | head -2
```

```output
  retireTask: (taskId: string) =>
  retireDone: (projectId: string) =>
```

## Column has Retire buttons

```bash
grep -c "retire" frontend/src/components/Column.tsx
```

```output
7
```

## SSE events defined

```bash
grep "RETIRED" src/shared/events.py
```

```output
    TASK_RETIRED = "task_retired"
    BULK_RETIRED = "bulk_retired"
```

## Migration exists

```bash
head -4 src/alembic/versions/4cab82be967b_add_retired_to_tasks.py
```

```output
"""add_retired_to_tasks

Revision ID: 4cab82be967b
Revises: f5a6b7c8d9e2
```

## Backend retire tests pass

```bash
cd /home/sachin/code/cloglog/.claude/worktrees/wt-ui-retire && uv run pytest tests/board/test_routes.py -q -k "retire" --tb=no 2>&1 | grep -oP "\d+ passed" | head -1
```

```output
8 passed
```

## Frontend tests pass

```bash
cd /home/sachin/code/cloglog/.claude/worktrees/wt-ui-retire/frontend && NO_COLOR=1 npx vitest run --reporter=dot 2>&1 | grep -E "Test Files|Tests " | head -2
```

```output
 Test Files  24 passed (24)
      Tests  198 passed (198)
```
