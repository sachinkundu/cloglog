# cloglog: A Multi-Agent Kanban for Autonomous AI Coding

> *What if your coding agents could manage themselves — while you reviewed PRs from your phone?*

---

## The Problem

You have five AI coding agents. They're working across different git branches, each building a feature. One is writing a design spec. Another is implementing an API. A third is building the frontend. They need tasks assigned, progress tracked, PRs reviewed, and coordination when their work overlaps.

Without cloglog, you're juggling terminal windows, manually checking heartbeats, and hoping agents don't step on each other's toes. With cloglog, you open a real-time dashboard, see every agent's status, drag tasks between columns, and review PRs — all while the agents self-coordinate through a shared board.

cloglog is a **multi-project Kanban dashboard** purpose-built for managing autonomous AI coding agents. It combines project planning (epics, features, tasks) with agent lifecycle management (registration, heartbeat, messaging, shutdown) in a single system that updates in real-time via Server-Sent Events.

```
 You (human)                          Your Agents
 +-----------+                        +-----------+
 | Dashboard | <-------- SSE -------> | MCP Tools |
 | (React)   |                        | (stdio)   |
 +-----------+                        +-----------+
       |                                    |
       | X-Dashboard-Key             Bearer + X-MCP-Request
       |                                    |
       v                                    v
 +--------------------------------------------------+
 |              cloglog Backend (FastAPI)             |
 |                                                    |
 |  +--------+  +-------+  +--------+  +---------+  |
 |  | Board  |  | Agent |  |Document|  | Gateway |  |
 |  +--------+  +-------+  +--------+  +---------+  |
 +--------------------------------------------------+
                        |
                   PostgreSQL
```

---

## Architecture: Four Bounded Contexts

cloglog follows **Domain-Driven Design** with four bounded contexts. Each context owns its models, services, repository, and routes. They communicate through Protocol interfaces — never by importing each other's internals.

```
 +------------------------------------------------------------------+
 |                         Gateway                                   |
 |  (API composition, auth middleware, SSE, CLI)                     |
 |  Composes routers from all contexts into a single FastAPI app     |
 +------------------------------------------------------------------+
        |                    |                    |
        v                    v                    v
 +--------------+   +--------------+   +------------------+
 |    Board     |   |    Agent     |   |    Document      |
 |              |   |              |   |                  |
 | Projects     |   | Worktrees    |   | Append-only      |
 | Epics        |   | Sessions     |   | document store   |
 | Features     |   | Heartbeat    |   |                  |
 | Tasks        |   | Messages     |   | Attached to      |
 | Dependencies |   | Shutdown     |   | epics, features, |
 | Notifications|   |              |   | or tasks         |
 +--------------+   +--------------+   +------------------+
        ^                    |
        |   Conformist       |
        +--------------------+
   Agent follows Board's
   TaskStatusService protocol
```

### Context Relationships

| Relationship | Pattern | What it means |
|---|---|---|
| Agent -> Board | **Conformist** | Agent adopts Board's task model wholesale. No translation layer. |
| Document -> Board | **Shared Kernel** | Document stores entity IDs (`attached_to_id`) but never queries Board tables directly. |
| Gateway -> All | **Open Host Service** | Gateway publishes a unified API that composes all contexts. |

### Why DDD?

Each context can be developed in an **isolated git worktree** by a separate agent. The Board agent can't accidentally break Agent code because they're in different directories, enforced by Claude Code hooks that block writes outside assigned paths.

```
src/
 +-- board/          # Board agent's territory
 |   +-- models.py
 |   +-- repository.py
 |   +-- services.py
 |   +-- routes.py
 |   +-- schemas.py
 |   +-- interfaces.py
 |
 +-- agent/          # Agent agent's territory
 |   +-- models.py
 |   +-- repository.py
 |   +-- services.py
 |   +-- routes.py
 |   +-- schemas.py
 |   +-- interfaces.py
 |
 +-- document/       # Document agent's territory
 |   +-- (same structure)
 |
 +-- gateway/        # Gateway agent's territory
 |   +-- app.py
 |   +-- auth.py
 |   +-- sse.py
 |   +-- cli.py
 |   +-- notification_listener.py
 |
 +-- shared/         # Shared kernel
     +-- database.py    # AsyncSession factory, Base class
     +-- config.py      # Pydantic settings
     +-- events.py      # EventBus, EventType enum
```

### The Interface Contracts

Contexts expose **Protocol classes** that define what they offer to other contexts:

```python
# src/board/interfaces.py — Board exposes to Agent
class TaskAssignmentService(Protocol):
    async def assign_task_to_worktree(self, task_id: UUID, worktree_id: UUID) -> None: ...
    async def unassign_task_from_worktree(self, task_id: UUID) -> None: ...
    async def get_tasks_for_worktree(self, worktree_id: UUID) -> list[dict]: ...

class TaskStatusService(Protocol):
    async def start_task(self, task_id: UUID, worktree_id: UUID) -> dict: ...
    async def complete_task(self, task_id: UUID) -> dict | None: ...
    async def update_task_status(self, task_id: UUID, status: str) -> None: ...

# src/agent/interfaces.py — Agent exposes to Gateway
class WorktreeService(Protocol):
    async def get_worktrees_for_project(self, project_id: UUID) -> list[dict]: ...
    async def get_worktree(self, worktree_id: UUID) -> dict | None: ...

# src/document/interfaces.py — Document exposes to Gateway
class DocumentService(Protocol):
    async def get_documents_for_entity(self, type: str, id: UUID) -> list[dict]: ...
    async def get_document(self, document_id: UUID) -> dict | None: ...
```

---

## The Data Model

### Board Hierarchy

Every piece of work lives in a four-level hierarchy:

```
Project
 +-- Epic  (bounded context or large initiative)
 |    +-- Feature  (deliverable unit of work)
 |    |    +-- Task  (atomic work item — what agents actually do)
 |    |    |    +-- TaskNote  (status updates, test reports)
 |    |    +-- Task
 |    +-- Feature
 |         +-- Task
 +-- Epic
      +-- Feature
           +-- Task
```

Each entity gets a **human-readable number** (E-1, F-5, T-23) via monotonic counters on the Project. UUIDs handle identity; numbers handle conversation.

### Task Types and the Pipeline

Tasks aren't all equal. The `task_type` field determines pipeline ordering:

| Type | Pipeline Stage | Description |
|------|---------------|-------------|
| `spec` | 0 | Write a design specification |
| `plan` | 1 | Write an implementation plan |
| `impl` | 2 | Implement the feature |
| `task` | -1 (independent) | Generic standalone task |

**Pipeline guards** enforce ordering. You can't start a `plan` task until all `spec` tasks in the same feature are done. You can't start `impl` until all `plan` tasks are done. This is the planning pipeline: **spec -> plan -> implement**.

### Status State Machine

```
                    +----------+
                    | backlog  |  (not started)
                    +----+-----+
                         |
                    start_task()
                         |
                    +----v-------+
                    | in_progress|  (agent working)
                    +----+-------+
                         |
                  update_task_status()
                         |
                    +----v-----+
                    |  review  |  (PR created, awaiting human)
                    +----+-----+
                         |
                    [human drags card]
                         |
                    +----v-----+
                    |   done   |  (complete)
                    +----------+
```

**Key constraint:** Agents can move tasks to `review` but **cannot** move them to `done`. Only humans drag the card to done on the dashboard. This ensures human review of every piece of agent work.

### Status Roll-Up

Feature and epic statuses are **computed**, not set directly:

```python
# Feature status = f(task statuses)
if all tasks done        -> "done"
elif any task in review  -> "review"
elif any task in_progress -> "in_progress"
else                     -> "planned"

# Epic status = f(feature statuses)
# Same logic, one level up
```

This means the board always reflects reality. No stale "in progress" epics with all-done tasks.

### Feature Dependencies

Features can depend on other features, forming a **directed acyclic graph**:

```
F-1 (Auth API)  ----+
                     |---> F-3 (Protected Routes)
F-2 (User Model) ---+

F-4 (Dashboard) --------> F-5 (SSE Integration)
```

Cycle detection via DFS prevents circular dependencies. The dependency graph is available as a visualization endpoint for the dashboard.

---

## The Agent Lifecycle

This is the heart of cloglog — how autonomous coding agents register, work, communicate, and shut down.

```mermaid
sequenceDiagram
    participant A as Agent (Claude Code)
    participant M as MCP Server (stdio)
    participant B as cloglog Backend
    participant D as Dashboard (SSE)

    Note over A,M: Session Start
    A->>M: register_agent(worktree_path)
    M->>B: POST /agents/register
    B->>B: Upsert worktree, create session
    B-->>D: SSE: WORKTREE_ONLINE
    B-->>M: {worktree_id, session_id, current_task}
    M-->>A: Registration confirmed

    Note over A,M: Work Loop
    loop Every 60 seconds
        M->>B: POST /agents/{id}/heartbeat
        B-->>M: {shutdown_requested, pending_messages}
    end

    A->>M: start_task(task_id)
    M->>B: POST /agents/{id}/start-task
    B->>B: Pipeline guard check
    B-->>D: SSE: TASK_STATUS_CHANGED
    B-->>M: {task_id, status: "in_progress"}

    Note over A: Agent writes code, runs tests...

    A->>M: update_task_status(task_id, "review", pr_url)
    M->>B: PATCH /agents/{id}/task-status
    B-->>D: SSE: TASK_STATUS_CHANGED
    B->>B: Create notification
    B-->>D: SSE: NOTIFICATION_CREATED

    Note over D: Human reviews PR, drags card to Done

    A->>M: unregister_agent()
    M->>B: POST /agents/{id}/unregister
    B->>B: End session, delete worktree
    B-->>D: SSE: WORKTREE_OFFLINE
```

### Registration

When an agent starts in a worktree, it calls `register_agent` with its filesystem path. The backend either creates a new worktree record or reconnects to an existing one (matching on `project_id + worktree_path`). This enables crash recovery — an agent that times out can re-register on the same path and pick up where it left off.

```python
# What happens inside register()
worktree, is_new = await repo.upsert_worktree(project_id, path, branch)
if not is_new:
    # End any stale sessions from previous connection
    old_session = await repo.get_active_session(worktree.id)
    if old_session:
        await repo.end_session(old_session.id, status="ended")

session = await repo.create_session(worktree.id)
# Returns current_task if resuming interrupted work
```

### Heartbeat

The MCP server sends a heartbeat every 60 seconds. The heartbeat response carries two critical signals:

1. **`shutdown_requested`** — the human (or main agent) wants this agent to stop
2. **`pending_messages`** — messages from other agents, piggybacked on the polling

If an agent's heartbeat goes silent for **180 seconds** (configurable), the backend marks the session as `timed_out` and the worktree as `offline`. A background scheduler checks for timeouts every 60 seconds.

### Three-Tier Shutdown

```
Tier 1: Cooperative                    Tier 2: SIGTERM              Tier 3: Timeout
+---------------------------+   +-------------------------+   +------------------+
| Main agent calls          |   | Process killed           |   | No heartbeat for |
| request-shutdown          |   | externally               |   | 180 seconds      |
|                           |   |                          |   |                  |
| Agent sees flag on next   |   | SessionEnd hook fires:   |   | Scheduler marks  |
| heartbeat, finishes work, |   | - Generate artifacts     |   | session timed_out|
| generates artifacts,      |   | - Call unregister-by-path|   | - Worktree offline|
| calls unregister          |   |   (best-effort)          |   | - WORKTREE_OFFLINE|
+---------------------------+   +-------------------------+   +------------------+
```

---

## The MCP Server: Agent Gateway

Agents don't talk to the cloglog API directly. They use **MCP tools** (Model Context Protocol) via a stdio-based server that acts as a gateway.

### Why MCP?

Claude Code (and other AI coding tools) natively support MCP. The agent calls a tool like `start_task` the same way it calls `Read` or `Edit` — it's part of the tool ecosystem. No curl commands, no HTTP clients, no auth token management.

### Authentication Flow

```
 Agent Process
 +-------------------+
 | Claude Code       |
 |                   |
 | Calls MCP tool:   |
 | start_task(...)   |
 +--------+----------+
          | JSON-RPC over stdio
          v
 +-------------------+
 | MCP Server        |
 | (Node.js)         |
 |                   |
 | Adds headers:     |
 | Authorization:    |
 |   Bearer <key>    |
 | X-MCP-Request:    |
 |   true            |
 +--------+----------+
          | HTTP
          v
 +-------------------+
 | cloglog Backend   |
 |                   |
 | Middleware checks: |
 | Has Bearer token? |
 | Has X-MCP-Request?|
 | -> Full access    |
 +-------------------+
```

The **three-credential model** ensures separation of concerns:

| Credential | Who | Access |
|---|---|---|
| `Authorization: Bearer <key>` | Agent directly | Only `/agents/*` routes |
| `Bearer <key>` + `X-MCP-Request: true` | MCP server (on behalf of agent) | All routes |
| `X-Dashboard-Key: <secret>` | Human dashboard/CLI | Non-agent routes |

Agents can only call `/agents/*` directly (register, heartbeat). For everything else (board, tasks, documents), they must go through MCP. This means the MCP server is the **single point of agent access control**.

### MCP Tool Reference

The MCP server exposes 20 tools organized by function:

**Agent Lifecycle**
| Tool | Description |
|---|---|
| `register_agent` | Register worktree, start session, begin heartbeat |
| `unregister_agent` | Clean shutdown, stop heartbeat |

**Task Management**
| Tool | Description |
|---|---|
| `get_my_tasks` | List tasks assigned to this worktree |
| `start_task` | Move task to in_progress (with pipeline guards) |
| `complete_task` | BLOCKED — agents cannot mark done |
| `update_task_status` | Move task between columns |
| `add_task_note` | Append status note to a task |

**Board Operations**
| Tool | Description |
|---|---|
| `get_board` | Kanban view — tasks by status column |
| `get_backlog` | Hierarchical tree — epics > features > tasks |
| `get_active_tasks` | Compact list of non-done tasks |
| `create_epic` | Create a new epic |
| `create_feature` | Create a feature under an epic |
| `create_task` | Create a task under a feature |
| `create_tasks` | Bulk import epics/features/tasks |
| `list_epics` | List all epics |
| `list_features` | List features in an epic |
| `update_task` | Edit task title/description/priority |
| `delete_task` | Remove a task |

**Documents & Messaging**
| Tool | Description |
|---|---|
| `attach_document` | Read local file, attach to entity on board |
| `send_agent_message` | Send message to another agent via heartbeat |

---

## Cross-Session Messaging

How does the main agent tell a worktree agent to rebase? How does one agent ask another about a shared interface?

cloglog uses **heartbeat-piggybacked messaging**. No WebSockets, no separate channels — messages ride on the existing polling mechanism.

```mermaid
sequenceDiagram
    participant Main as Main Agent
    participant B as Backend
    participant W as Worktree Agent

    Main->>B: POST /agents/{worktree_id}/message
    Note over B: Queue AgentMessage<br/>(delivered=false)
    B-->>Main: 202 Accepted

    Note over W: 60 seconds later...

    W->>B: POST /agents/{id}/heartbeat
    B->>B: Drain pending messages<br/>Mark delivered=true
    B-->>W: {pending_messages: ["[main-agent] please rebase on main"]}

    Note over W: Agent reads message<br/>in tool response
```

### Message Delivery Guarantees

- **At-most-once delivery**: Messages are drained on read and marked delivered. If the agent crashes before processing, the message is lost.
- **FIFO ordering**: Messages delivered in creation order.
- **Up to 60s latency**: Messages wait for the next heartbeat cycle.
- **Sender tagging**: Each message includes sender identity (`main-agent`, `system`, worktree ID).

Messages appear in the agent's tool response with a prefix:

```
📨 MESSAGES:
- [main-agent] please rebase on main before pushing
- [wt-frontend] I updated the API types, pull latest
```

### What Was Tried and Failed

**`sendLoggingMessage`** (MCP protocol logging): The MCP SDK's built-in logging mechanism was attempted first. It failed because logging messages are fire-and-forget with no delivery confirmation, no storage, and no way to target specific agents. The heartbeat piggyback approach was adopted because it uses the existing polling infrastructure agents already depend on.

---

## The Board & Dashboard

The React dashboard is a real-time Kanban board that updates live as agents work.

### Board Layout

```
 +------------------------------------------------------------------+
 | Sidebar          | Board                                          |
 |                  |                                                |
 | Projects         | Backlog    In Progress   Review     Done      |
 | +- Project A     | +-------+ +----------+ +--------+ +--------+ |
 | +- Project B     | | T-12  | | T-8      | | T-5    | | T-1    | |
 |                  | | Setup | | Add auth | | PR #42 | | Scaffold| |
 | Agents           | |       | | wt-agent | |        | |        | |
 | * wt-board  [ON] | +-------+ +----------+ +--------+ +--------+ |
 | * wt-agent  [ON] | | T-15  | | T-11     | | T-9    | | T-3    | |
 | * wt-front [OFF] | | Docs  | | Build UI | | PR #45 | | Models | |
 |                  | +-------+ +----------+ +--------+ +--------+ |
 |                  |                                                |
 | Search [____]    | Backlog Tree (expandable)                     |
 | Notifications    | E-1 Board Context                              |
 |                  |   F-1 Task Management                          |
 |                  |     T-1 Models [done]                          |
 |                  |     T-2 Routes [review]                        |
 |                  |   F-2 Search                                   |
 |                  |     T-5 Implement [in_progress]                |
 +------------------------------------------------------------------+
```

### Real-Time SSE Updates

The dashboard subscribes to a Server-Sent Events stream:

```
GET /api/v1/projects/{project_id}/stream
```

The backend publishes 18 event types through an in-memory EventBus:

```python
class EventBus:
    """Simple in-process pub/sub for SSE fan-out."""

    async def publish(self, event: Event) -> None:
        # Fan out to project-specific subscribers
        for queue in self._subscribers.get(event.project_id, []):
            await queue.put(event)
        # Fan out to global subscribers (notification listener)
        for queue in self._global_subscribers:
            await queue.put(event)
```

When an agent changes a task status, the event flows:

```
Agent calls update_task_status()
  -> Backend publishes TASK_STATUS_CHANGED event
    -> SSE endpoint yields event to dashboard
      -> React hook updates board state
        -> Task card moves between columns (no page refresh)
```

The frontend `useSSE` hook handles 14 event types with targeted state updates:

| Event | Dashboard Action |
|---|---|
| `task_status_changed` | Move task card between columns |
| `worktree_online` / `worktree_offline` | Update agent status indicator |
| `document_attached` | Refresh detail panel |
| `notification_created` | Show notification bell |
| `epic/feature/task_created` | Refresh backlog tree |
| `dependency_added/removed` | Refresh dependency graph |
| `bulk_import` | Full board refresh |

### Drag-and-Drop

The board supports drag-and-drop via `@dnd-kit`:

- **Kanban columns**: Drag tasks between status columns (with optimistic UI)
- **Backlog tree**: Reorder epics, features, and tasks within their containers
- **Touch support**: Works on mobile via PointerSensor + TouchSensor

### Notifications

When a task moves to `review`, a background listener creates a notification:

```python
# notification_listener.py runs during app lifespan
async def run_notification_listener():
    queue = event_bus.subscribe_all()
    while True:
        event = await queue.get()
        if event.type == EventType.TASK_STATUS_CHANGED:
            if event.data.get("new_status") == "review":
                # Create DB notification
                # Publish NOTIFICATION_CREATED event
                # Fire desktop notification via notify-send
```

This means you get notified the moment an agent puts up a PR for review — even as a desktop notification if you're on Linux.

---

## Reconciliation

Distributed systems drift. Agents crash, PRs merge without board updates, worktrees get orphaned. The `/reconcile` skill detects and fixes this drift.

### What It Checks

| Check | Drift Type | Fix |
|---|---|---|
| Board tasks in `review` but PR merged | Board behind GitHub | Move task to `done` |
| Worktrees marked `online` with no heartbeat | Stale agent state | Mark offline |
| Git branches with no matching worktree | Orphaned branches | Flag for cleanup |
| Worktree directories that don't exist | Stale DB records | Remove record |
| Tasks assigned to offline worktrees | Abandoned work | Unassign |

Reconciliation is triggered manually via the `/reconcile` command. It's designed to be safe — it reports what it finds and asks for confirmation before fixing.

---

## Infrastructure: Worktree Isolation

Each agent works in complete isolation: its own git branch, its own ports, its own database.

### Worktree Setup

```bash
./scripts/create-worktree.sh <name> <context>
```

This script:

1. Creates a git worktree at `.claude/worktrees/wt-<name>`
2. Checks out a new branch `wt-<name>`
3. Assigns **deterministic ports** by hashing the worktree name
4. Creates an **isolated PostgreSQL database** named `cloglog_wt_<name>`
5. Runs Alembic migrations on the new database
6. Writes a `.env` file with the worktree's port and database URL
7. Generates a worktree-specific `CLAUDE.md` with directory restrictions
8. Installs dependencies (Python via `uv`, Node via `npm`)

### Port Allocation

```bash
# scripts/worktree-ports.sh
# Deterministic ports from worktree name hash
HASH=$(echo -n "$WORKTREE_NAME" | md5sum | cut -c1-8)
HASH_NUM=$((16#$HASH % 50000 + 10000))

export BACKEND_PORT=$HASH_NUM
export FRONTEND_PORT=$((HASH_NUM + 1))
```

No port conflicts between worktrees. No hardcoded ports. Every worktree gets its own backend, frontend, and database.

### Infrastructure Lifecycle

```
create-worktree.sh up          manage-worktrees.sh remove
        |                               |
        v                               v
 Create DB -----> Run migrations   Kill processes
 Assign ports     Write .env       Drop database
 Install deps     Generate CLAUDE  Remove .env
                                   Delete worktree + branch
```

### Bot Identity for PRs

All agent pushes and PR creation use a **GitHub App bot identity**, never the user's personal account:

```bash
BOT_TOKEN=$(uv run --with "PyJWT[crypto]" --with requests \
  ~/.agent-vm/credentials/gh-app-token.py)

git remote set-url origin \
  "https://x-access-token:${BOT_TOKEN}@github.com/owner/repo.git"
git push -u origin HEAD

GH_TOKEN="$BOT_TOKEN" gh pr create --title "feat: ..." --body "..."
```

This means every PR shows as authored by the bot, not the human — which matters because the human needs to be able to review and merge their own agents' work.

---

## Hook-Enforced Discipline

cloglog uses **Claude Code hooks** — shell scripts that run before tool calls — to enforce rules that agents can't bypass.

### Active Hooks

| Hook | Trigger | What it enforces |
|---|---|---|
| `protect-worktree-writes.sh` | Any file Edit/Write | Agent can only modify files in its assigned context |
| `quality-gate-before-commit.sh` | `git commit`, `git push`, `gh pr create` | Must pass `make quality` (lint + typecheck + test + coverage + contract) |
| `prefer-mcp-over-api.sh` | `curl`/`wget` to localhost API | Blocks direct API calls, enforces MCP tool use |
| `enforce-task-transitions.sh` | MCP task status updates | Prevents skipping review (must go through review before done) |
| `agent-shutdown.sh` | Session end (SIGTERM) | Generates work logs, calls unregister-by-path |

### Worktree Write Protection

The protect-worktree-writes hook maps worktree names to allowed directories:

```bash
# protect-worktree-writes.sh (simplified)
case "$BRANCH" in
  wt-board*)    ALLOWED="src/board/ tests/board/ src/alembic/" ;;
  wt-agent*)    ALLOWED="src/agent/ tests/agent/ src/alembic/" ;;
  wt-frontend*) ALLOWED="frontend/" ;;
  wt-mcp*)      ALLOWED="mcp-server/" ;;
  wt-e2e*)      ALLOWED="tests/e2e/" ;;
esac
# Block writes to any path not in ALLOWED
```

This means an agent working on the Board context literally cannot write to Agent context files. The hook intercepts the tool call and returns an error before the write happens.

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| Backend Framework | **FastAPI** | Async-native, Pydantic integration, OpenAPI generation |
| Database | **PostgreSQL 16** | Reliable, async support via asyncpg, JSONB for metadata |
| ORM | **SQLAlchemy 2.0** (async) | Type-safe queries, relationship loading, Alembic migrations |
| Migrations | **Alembic** | Reliable schema versioning across worktrees |
| Real-time | **SSE Starlette** | Server-Sent Events for dashboard live updates |
| Frontend | **React 18 + Vite** | Fast dev builds, component model, TypeScript |
| Drag-and-Drop | **@dnd-kit** | Accessible, composable DnD primitives |
| MCP Server | **Node.js + @modelcontextprotocol/sdk** | Native MCP support, stdio transport |
| CLI | **Typer + Rich** | Beautiful terminal UI for human operators |
| Package Manager | **uv** | Fast Python dependency resolution |
| Linting | **Ruff** | Fast Python linting and formatting |
| Type Checking | **mypy** (with SQLAlchemy plugin) | Catch type errors in async DB code |
| Testing | **pytest** (backend), **Vitest** (frontend), **Playwright** (E2E) | Full test pyramid |
| API Contract | **OpenAPI YAML** | Single source of truth for API shape |

### Type Safety Pipeline

```
OpenAPI YAML contract
  |
  | generate-contract-types.sh
  v
frontend/src/api/generated-types.ts
  |
  | import
  v
React components use typed API responses
```

Frontend never hand-writes API types. Backend runs `make contract-check` to verify endpoints match the contract. Drift is caught before commit.

---

## Getting Started

### Prerequisites

- Python 3.12+
- Node.js 20+
- PostgreSQL 16+
- Docker (for easy DB setup)
- [uv](https://github.com/astral-sh/uv) (Python package manager)

### Quick Start

```bash
# Clone the repo
git clone https://github.com/sachinkundu/cloglog.git
cd cloglog

# Install Python dependencies
uv sync --all-extras

# Start PostgreSQL and run migrations
make db-up
make db-migrate

# Start the backend (http://localhost:8000)
make run-backend

# In another terminal, start the frontend (http://localhost:5173)
cd frontend && npm install && npm run dev
```

### Running Tests

```bash
# Full quality gate (lint + typecheck + test + coverage + contract)
make quality

# Individual checks
make test           # All backend tests
make lint           # Ruff linter
make typecheck      # mypy

# Frontend tests (must run from frontend/)
cd frontend && npx vitest run

# MCP server tests
cd mcp-server && make test
```

### See It In Action

1. Open the dashboard at `http://localhost:5173`
2. Create a project
3. Use the CLI to add epics, features, and tasks:
   ```bash
   cloglog projects create "My Project"
   ```
4. Configure the MCP server in your Claude Code settings:
   ```json
   {
     "mcpServers": {
       "cloglog": {
         "command": "node",
         "args": ["./mcp-server/dist/index.js"],
         "env": {
           "CLOGLOG_URL": "http://localhost:8000",
           "CLOGLOG_API_KEY": "<your-project-api-key>"
         }
       }
     }
   }
   ```
5. Start Claude Code in a worktree — it registers automatically and begins working tasks from the board

---

## Contributing

### Where to Start

The codebase is organized so you can contribute to one context without understanding the others:

| I want to... | Look at... |
|---|---|
| Add a board feature (new column, filter, etc.) | `src/board/` + `frontend/src/components/Board.tsx` |
| Add an agent capability | `src/agent/` + `mcp-server/src/server.ts` |
| Add a new MCP tool | `mcp-server/src/server.ts` (tool definition) + `mcp-server/src/tools.ts` (handler) |
| Add a dashboard component | `frontend/src/components/` |
| Add a new API endpoint | Context's `routes.py` + register in `src/gateway/app.py` |
| Add a database migration | `alembic revision --autogenerate -m "description"` |

### Adding a New MCP Tool

1. Define the tool schema in `mcp-server/src/server.ts` with Zod validation:
   ```typescript
   server.tool("my_tool", "Description", { param: z.string() }, async (args) => {
     const result = await client.request("POST", "/api/v1/...", args);
     return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
   });
   ```

2. Add the backend endpoint in the appropriate context's `routes.py`

3. Register the router in `src/gateway/app.py` if it's a new context

### Adding a Board Feature

1. Add the model/field in `src/board/models.py`
2. Create a migration: `alembic revision --autogenerate -m "add field"`
3. Add repository method in `src/board/repository.py`
4. Add service logic in `src/board/services.py`
5. Add route in `src/board/routes.py`
6. Add schema in `src/board/schemas.py`
7. Publish events via `event_bus.publish()` for SSE updates
8. Update the frontend to consume the new data

### Testing Expectations

- **Backend**: Unit tests for services + integration tests for routes (against real PostgreSQL)
- **Frontend**: Component tests with `@testing-library/react` (test interactions, not just rendering)
- **E2E**: Playwright specs for critical user flows
- Every PR must include tests. `make quality` must pass. This is enforced by hooks.

### Worktree Development

For isolated development on a context:

```bash
# Create an isolated worktree for the board context
./scripts/create-worktree.sh my-feature board

# Work in the worktree
cd .claude/worktrees/wt-my-feature

# Your writes are restricted to src/board/, tests/board/, src/alembic/
# The hook will block writes to other contexts

# Clean up when done
./scripts/manage-worktrees.sh remove my-feature
```

---

## Glossary

| Term | Definition |
|---|---|
| **Worktree** | A git worktree + agent session. One worktree = one agent = one branch. |
| **Bounded Context** | A DDD boundary (Board, Agent, Document, Gateway) with its own models and rules. |
| **Pipeline** | The spec -> plan -> impl task ordering within a feature. |
| **Heartbeat** | 60-second HTTP poll from MCP server to backend, carrying shutdown signals and messages. |
| **Roll-up** | Automatic status computation from children (tasks -> feature -> epic). |
| **MCP** | Model Context Protocol — stdio-based tool interface for AI agents. |
| **SSE** | Server-Sent Events — one-way real-time stream from backend to dashboard. |
| **EventBus** | In-process pub/sub that fans events to SSE subscribers and the notification listener. |
| **Wave** | A batch of worktrees launched together to implement a set of features. |
| **Bot Identity** | GitHub App token used for all agent git operations. |
| **Quality Gate** | `make quality` — lint + typecheck + test + coverage + contract check. Must pass before commit. |

---

*cloglog is built by agents, for agents — and the humans who orchestrate them.*
