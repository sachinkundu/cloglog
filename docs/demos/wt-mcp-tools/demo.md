# T-125: Filtered Board Queries & get_active_tasks MCP Tool

The board endpoint previously returned all tasks (103K+ chars), overwhelming agent context windows. This adds filtering to reduce response size and a new compact endpoint for agent queries.

Verify the board route now accepts optional filter query parameters while remaining backward compatible (all default to no filtering):

```bash
sed -n '/^async def get_board/,/^async def/{ /status.*Query\|epic_id.*UUID.*None\|exclude_done.*bool/p }' src/board/routes.py
```

```output
    status: Annotated[list[str] | None, Query()] = None,
    epic_id: UUID | None = None,
    exclude_done: bool = False,
```

Verify the new active-tasks route exists with a compact response model:

```bash
grep "active-tasks" src/board/routes.py
```

```output
    "/projects/{project_id}/active-tasks",
```

Verify the repository layer supports the new get_active_tasks query that excludes done and archived tasks:

```bash
grep "def get_active_tasks" src/board/repository.py
```

```output
    async def get_active_tasks(self, project_id: UUID) -> list[Task]:
```

Verify the MCP server registers the new get_active_tasks tool with a clear description:

```bash
grep -A1 "'get_active_tasks'" mcp-server/src/server.ts
```

```output
    'get_active_tasks',
    'Get a compact list of non-done, non-archived tasks. Much smaller than get_board — use this when you only need task IDs, statuses, and titles.',
```

Verify the MCP get_board tool now accepts optional filter parameters for epic and done-exclusion:

```bash
grep "optional.*describe.*Filter\|optional.*describe.*Exclude" mcp-server/src/server.ts
```

```output
      epic_id: z.string().optional().describe('Filter to tasks under this epic UUID'),
      exclude_done: z.boolean().optional().describe('Exclude done tasks (default: false)'),
```
