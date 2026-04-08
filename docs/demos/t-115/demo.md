# T-115 Demo: MCP Server Guard Error Handling

## What Changed

1. **Error wrapping** — `start_task`, `complete_task`, and `update_task_status` now catch API errors (409 guard rejections) and return them as `isError: true` MCP responses instead of crashing.
2. **Description updates** — `update_task_status` now documents that `pr_url` is required for ALL task types moving to review (not just spec/impl). `start_task` documents the one-active-task and pipeline ordering guards.
3. **`create_task` already had `task_type`** — verified and tested.

## Guard Error Surfacing

The key behavioral change is in `server.ts` — guard rejections now return structured error responses instead of crashing:

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
