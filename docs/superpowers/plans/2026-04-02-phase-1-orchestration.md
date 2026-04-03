# Phase 1 Orchestration Guide

How to fire all 6 worktrees in parallel and merge them.

## Worktree Plans

| Worktree | Plan | Context | Depends On |
|----------|------|---------|------------|
| `wt-board` | `phase-1-board.md` | Board: models, CRUD, import, roll-up | None (go first) |
| `wt-gateway` | `phase-1-gateway.md` | Gateway: auth, SSE, CLI | Board |
| `wt-agent` | `phase-1-agent.md` | Agent: registration, heartbeat, lifecycle | Board |
| `wt-document` | `phase-1-document.md` | Document: append-only storage | Board, Gateway auth |
| `wt-frontend` | `phase-1-frontend.md` | Frontend: theme, sidebar, kanban, SSE | None (tests are mocked) |
| `wt-mcp` | `phase-1-mcp.md` | MCP server: all 9 tools | None (tests use mock HTTP) |

## Parallelism

```
                 ┌─ wt-frontend (independent, mocked tests)
                 │
wt-board ───────►├─ wt-gateway (needs board routes + models)
 (start first)   │
                 ├─ wt-agent (needs board models + services)
                 │
                 ├─ wt-document (needs board models + gateway auth)
                 │
                 └─ wt-mcp (independent, mock HTTP tests)
```

**Start `wt-board` first.** It creates the database tables and models that other backend contexts import. Once board is merged to main, rebase the other backend worktrees.

**`wt-frontend` and `wt-mcp` can start immediately** — they don't import any backend code. Their tests use mocks.

## How to Fire Each Worktree

Open 6 terminals. In each one:

```bash
# Terminal 1: Board (start this first)
cd /home/sachin/code/cloglog
scripts/create-worktree.sh wt-board
cd worktrees/wt-board
claude --dangerously-skip-permissions
# Then tell it: "Execute the plan at docs/superpowers/plans/2026-04-02-phase-1-board.md"

# Terminal 2: Frontend (can start immediately)
cd /home/sachin/code/cloglog
scripts/create-worktree.sh wt-frontend
cd worktrees/wt-frontend
claude --dangerously-skip-permissions
# Then tell it: "Execute the plan at docs/superpowers/plans/2026-04-02-phase-1-frontend.md"

# Terminal 3: MCP (can start immediately)
cd /home/sachin/code/cloglog
scripts/create-worktree.sh wt-mcp
cd worktrees/wt-mcp
claude --dangerously-skip-permissions
# Then tell it: "Execute the plan at docs/superpowers/plans/2026-04-02-phase-1-mcp.md"

# Terminal 4: Gateway (wait for board to merge, then start)
cd /home/sachin/code/cloglog
scripts/create-worktree.sh wt-gateway
cd worktrees/wt-gateway
# Wait until wt-board PR is merged, then:
git pull origin main
claude --dangerously-skip-permissions
# Then tell it: "Execute the plan at docs/superpowers/plans/2026-04-02-phase-1-gateway.md"

# Terminal 5: Agent (wait for board to merge, then start)
cd /home/sachin/code/cloglog
scripts/create-worktree.sh wt-agent
cd worktrees/wt-agent
# Wait until wt-board PR is merged, then:
git pull origin main
claude --dangerously-skip-permissions
# Then tell it: "Execute the plan at docs/superpowers/plans/2026-04-02-phase-1-agent.md"

# Terminal 6: Document (wait for board + gateway to merge, then start)
cd /home/sachin/code/cloglog
scripts/create-worktree.sh wt-document
cd worktrees/wt-document
# Wait until wt-board and wt-gateway PRs are merged, then:
git pull origin main
claude --dangerously-skip-permissions
# Then tell it: "Execute the plan at docs/superpowers/plans/2026-04-02-phase-1-document.md"
```

## Merge Order

1. **wt-board** — creates tables, models, routes (no dependencies)
2. **wt-gateway** — auth middleware, SSE, CLI (depends on board)
3. **wt-agent** — registration, heartbeat (depends on board)
4. **wt-document** — document storage (depends on board + gateway auth)
5. **wt-frontend** — React SPA (independent, merge anytime)
6. **wt-mcp** — MCP server (independent, merge anytime)

Frontend and MCP can merge in any order since they don't touch backend code.

## After All Merges — Integration Test

Once everything is on main:

```bash
# Start services
make db-up
make db-migrate
make run-backend &
cd frontend && npm run dev &

# Create a project
curl -X POST localhost:8000/api/v1/projects \
  -H "Content-Type: application/json" \
  -d '{"name": "test-project"}' | jq .

# Save the project ID and API key from the response

# Import a sample plan
curl -X POST localhost:8000/api/v1/projects/{PROJECT_ID}/import \
  -H "Content-Type: application/json" \
  -d '{
    "epics": [{
      "title": "Auth System",
      "features": [{
        "title": "Login",
        "tasks": [
          {"title": "Login form UI"},
          {"title": "Login API endpoint"},
          {"title": "Session management"}
        ]
      }, {
        "title": "Registration",
        "tasks": [
          {"title": "Signup form"},
          {"title": "Email verification"}
        ]
      }]
    }]
  }'

# Open http://localhost:5173 in browser
# Click the project in the sidebar
# Verify: 5 tasks in Backlog column, board header shows "5 tasks · 0 done · 0%"

# Register an agent
curl -X POST localhost:8000/api/v1/agents/register \
  -H "Authorization: Bearer {API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"worktree_path": "/home/user/wt-auth"}'

# Verify: agent appears in sidebar roster

# Start a task (use task ID from the board)
curl -X POST localhost:8000/api/v1/agents/{WT_ID}/start-task \
  -H "Authorization: Bearer {API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"task_id": "{TASK_ID}"}'

# Verify: task moves to "In Progress" column live (SSE)

# Attach a document
curl -X POST localhost:8000/api/v1/agents/{WT_ID}/documents \
  -H "Authorization: Bearer {API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "{TASK_ID}",
    "type": "spec",
    "title": "Login Flow Spec",
    "content": "# Login Flow\n\nUser enters email and password..."
  }'

# Click the task card — verify document appears in detail view

# Complete the task
curl -X POST localhost:8000/api/v1/agents/{WT_ID}/complete-task \
  -H "Authorization: Bearer {API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"task_id": "{TASK_ID}"}'

# Verify: task moves to "Done", stats update to "1 done"

# Run full quality gate
make quality
```
