# Agents and supervisor can now reorder tasks, features, and epics through MCP — the same drag-and-drop ordering operation the frontend already performs, now scriptable from any MCP client.

*2026-05-05T04:51:49Z by Showboat 0.6.1*
<!-- showboat-id: 7e1494dc-f5ce-4812-9ff0-5d99cc0a6e72 -->

Setup: rebuild mcp-server/dist so the demo exercises the freshly compiled handlers, not a stale build.

```bash
cd /home/sachin/code/cloglog/.claude/worktrees/wt-t394-mcp-position-reorder/mcp-server && npm run build >/dev/null 2>&1 && echo 'mcp-server build: OK'
```

```output
mcp-server build: OK
```

Before: prior to this change the MCP tool surface had no way to reorder backlog items — agents had to ask the user to drag cards in the UI. The new tools follow the same naming and project-scoped guarding as the rest of the board surface.

```bash
grep -oE "server\.tool\(\s*'reorder_[a-z]+'" /home/sachin/code/cloglog/.claude/worktrees/wt-t394-mcp-position-reorder/mcp-server/dist/server.js | sort -u
```

```output
server.tool('reorder_epics'
server.tool('reorder_features'
server.tool('reorder_tasks'
```

Action: instantiate the built tool handlers with a mock CloglogClient that records every request, then call reorder_epics / reorder_features / reorder_tasks. The recorded (method, URL, body) triples prove each tool forwards to the correct backend route.

```bash
cd /home/sachin/code/cloglog/.claude/worktrees/wt-t394-mcp-position-reorder/mcp-server && node --input-type=module -e "
import { createToolHandlers } from './dist/tools.js';
const calls = [];
const client = { request: async (m, u, b) => { calls.push({m, u, b}); return { status: 'ok' }; } };
const h = createToolHandlers(client);
await h.reorder_epics({ project_id: 'P', items: [{id:'e1',position:0},{id:'e2',position:1000}] });
await h.reorder_features({ project_id: 'P', epic_id: 'E', items: [{id:'f1',position:0}] });
await h.reorder_tasks({ feature_id: 'F', items: [{id:'t1',position:0},{id:'t2',position:1000}] });
for (const c of calls) console.log(c.m, c.u, JSON.stringify(c.b));
"
```

```output
POST /api/v1/projects/P/epics/reorder {"items":[{"id":"e1","position":0},{"id":"e2","position":1000}]}
POST /api/v1/projects/P/epics/E/features/reorder {"items":[{"id":"f1","position":0}]}
POST /api/v1/features/F/tasks/reorder {"items":[{"id":"t1","position":0},{"id":"t2","position":1000}]}
```

After: the URLs match the drag-and-drop endpoints in src/board/routes.py (reorder_epics / reorder_features / reorder_tasks) — agents now hit the same code path the frontend BacklogTree already exercises.

```bash
grep -oE '@router\.post\("[^"]*reorder"\)' /home/sachin/code/cloglog/.claude/worktrees/wt-t394-mcp-position-reorder/src/board/routes.py | sort
```

```output
@router.post("/features/{feature_id}/tasks/reorder")
@router.post("/projects/{project_id}/epics/{epic_id}/features/reorder")
@router.post("/projects/{project_id}/epics/reorder")
```

Pin: vitest covers both the handler layer (tools.test.ts) and the registered tool layer (server.test.ts). The summary line below shows all 149 mcp-server tests passing — the +8 over baseline are this PR's reorder coverage.

```bash
cd /home/sachin/code/cloglog/.claude/worktrees/wt-t394-mcp-position-reorder/mcp-server && npm test --silent 2>&1 | grep -oE 'Tests +[0-9]+ passed \([0-9]+\)' | head -1
```

```output
Tests  149 passed (149)
```
