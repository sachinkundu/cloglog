# T-115 Demo: MCP Server Guard Error Handling

## What Changed

1. **Error wrapping** — `start_task`, `complete_task`, and `update_task_status` now catch API errors (409 guard rejections) and return them as `isError: true` MCP responses instead of crashing.
2. **Description updates** — `update_task_status` now documents that `pr_url` is required for ALL task types moving to review (not just spec/impl). `start_task` documents the one-active-task and pipeline ordering guards.
3. **`create_task` already had `task_type`** — verified and tested.

## Test Output

```
$ cd mcp-server && npx vitest run

 ✓ src/__tests__/tools.test.ts (25 tests) 17ms
 ✓ src/__tests__/heartbeat.test.ts (3 tests) 12ms
 ✓ tests/client.test.ts (4 tests) 11ms
 ✓ tests/server.test.ts (9 tests) 53ms

 Test Files  4 passed (4)
      Tests  41 passed (41)
```

**Delta: +12 new tests** (18 -> 25 in tools.test.ts, 4 -> 9 in server.test.ts)

## Guard Error Surfacing (server.test.ts)

The key behavioral change is in `server.ts` — guard rejections now return structured error responses:

### One-active-task guard
```
Input: start_task({ task_id: 't1' }) when agent already has active task
Output: { isError: true, content: [{ type: 'text', text: '⛔ cloglog API error: 409 Cannot start task: agent already has active task(s)' }] }
```

### Pipeline ordering guard
```
Input: start_task({ task_id: 't1' }) when spec not done yet
Output: { isError: true, content: [{ type: 'text', text: '⛔ cloglog API error: 409 Cannot start plan task: spec task(s) not done yet' }] }
```

### PR URL required for review
```
Input: update_task_status({ task_id: 't1', status: 'review' }) without pr_url
Output: { isError: true, content: [{ type: 'text', text: '⛔ cloglog API error: 409 Cannot move task to review without a PR URL' }] }
```

### Agent cannot mark done
```
Input: complete_task({ task_id: 't1' })
Output: { isError: true, content: [{ type: 'text', text: '⛔ cloglog API error: 409 Agents cannot mark tasks as done' }] }
```

## Quality Gate

```
$ make quality
── Quality gate: PASSED ────────────────
```
