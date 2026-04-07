# T-125: Filtered Board Queries & get_active_tasks MCP Tool

Adds filtering support to get_board and a new lightweight get_active_tasks endpoint + MCP tool, reducing agent context consumption from 103K to under 1K characters.

```bash
grep -c "exclude_done\|epic_id\|statuses" src/board/repository.py
```

```output
28
```

```bash
grep "active.tasks\|ActiveTaskItem" src/board/routes.py | head -3
```

```output
    ActiveTaskItem,
    "/projects/{project_id}/active-tasks",
    response_model=list[ActiveTaskItem],
```

```bash
grep "get_active_tasks" mcp-server/src/tools.ts | head -2
```

```output
  get_active_tasks(args: { project_id: string }): Promise<unknown>
    async get_active_tasks({ project_id }) {
```

```bash
uv run pytest tests/board/test_routes.py -k "board_no_filters or board_exclude_done or board_filter_by_status or board_filter_by_epic or board_combined_filters or active_tasks_endpoint or active_tasks_excludes_archived or active_tasks_not_found" -q 2>&1 | grep -oP "\d+ passed"
```

```output
8 passed
```

```bash
cd mcp-server && npx vitest run src/__tests__/tools.test.ts 2>&1 | grep -oP "Tests\s+\d+ passed"
```

```output
Tests  12 passed
```
