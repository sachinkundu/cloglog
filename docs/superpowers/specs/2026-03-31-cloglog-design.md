# cloglog — Multi-Project Agent Dashboard

**Date:** 2026-03-31
**Status:** Design

## Overview

cloglog is a Kanban-style dashboard for managing autonomous AI coding agents running inside agent-vm sandboxes. It provides a single place to see all projects, which agents (worktrees) are active, what tasks they're working on, and the full history of design artifacts behind each task.

The system has three parts:
1. **cloglog service** — FastAPI backend + PostgreSQL, runs on the host machine
2. **cloglog frontend** — React SPA, served by the backend or standalone
3. **cloglog-mcp** — lightweight MCP server installed inside agent-vm base image, gives agents tools to report status and attach documents

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Host Machine                                        │
│                                                      │
│  ┌──────────────┐     ┌──────────────────────────┐  │
│  │  cloglog      │     │  React Frontend          │  │
│  │  FastAPI       │◄───│  (Kanban board, project   │  │
│  │  + PostgreSQL  │     │   selector, doc viewer)  │  │
│  └──────┬───────┘     └──────────────────────────┘  │
│         │ REST API                                    │
│         │ SSE (real-time updates)                     │
├─────────┼────────────────────────────────────────────┤
│         ▼                                            │
│  ┌─────────────────┐  ┌─────────────────┐           │
│  │  agent-vm (proj1)│  │  agent-vm (proj2)│  ...     │
│  │                  │  │                  │           │
│  │  cloglog-mcp ────┼──┼── HTTP POST ────►           │
│  │  Claude Code     │  │  Claude Code     │           │
│  │  (worktree A)    │  │  (worktree X)    │           │
│  │  (worktree B)    │  │  (worktree Y)    │           │
│  └──────────────────┘  └──────────────────┘           │
└──────────────────────────────────────────────────────┘
```

Agents inside agent-vm sandboxes communicate with the cloglog service via HTTP. The MCP server reads `CLOGLOG_URL` and `CLOGLOG_API_KEY` from environment variables. agent-vm's networking allows VMs to reach the host.

## Data Model

### Project

Top-level entity. Maps 1:1 to a source code repository and an agent-vm instance.

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| name | string | Project name (e.g., "cloglog") |
| description | text | Optional project description |
| repo_url | string | Optional repository URL |
| api_key_hash | string | Hashed API key for agent auth |
| status | enum | active / paused / completed |
| created_at | timestamp | |

### Epic

Large initiative, optionally maps to a DDD Bounded Context.

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| project_id | FK → Project | Parent project |
| title | string | Epic name |
| description | text | |
| bounded_context | string | Optional DDD Bounded Context label |
| context_description | text | Optional ubiquitous language / domain boundaries |
| status | enum | planned / in_progress / done |
| position | int | Display order |
| created_at | timestamp | |

Status is a cached roll-up, recomputed whenever a child Feature's status changes: all features done → epic done, any feature in_progress → epic in_progress, otherwise planned.

### Feature

Deliverable unit of work under an Epic.

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| epic_id | FK → Epic | Parent epic |
| title | string | Feature name |
| description | text | |
| status | enum | planned / in_progress / review / done |
| position | int | Display order within epic |
| created_at | timestamp | |

Status is a cached roll-up, recomputed whenever a child Task's status changes: all tasks done → feature done, any task in review → feature in review, any task in_progress → feature in_progress, otherwise planned.

### Feature Dependency

Optional dependency between Features to help avoid merge conflicts and sequence work.

| Field | Type | Description |
|-------|------|-------------|
| feature_id | FK → Feature | The dependent feature |
| depends_on_id | FK → Feature | The feature it depends on |

### Task

Agent-sized work unit. This is what appears as a card on the Kanban board.

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| feature_id | FK → Feature | Parent feature |
| title | string | Task name |
| description | text | What needs to be done |
| status | enum | backlog / assigned / in_progress / review / done / blocked |
| priority | enum | normal / expedite |
| worktree_id | FK → Worktree | Assigned worktree (nullable) |
| position | int | Display order within column |
| created_at | timestamp | |
| updated_at | timestamp | |

### Worktree

Persistent agent identity. Tied to a git worktree path inside a VM. Survives session restarts.

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| project_id | FK → Project | Parent project (immutable) |
| name | string | Derived from worktree path |
| worktree_path | string | Path inside the VM |
| current_task_id | FK → Task | Currently active task (nullable) |
| status | enum | active / idle / offline |
| last_heartbeat | timestamp | Last time a session checked in |
| created_at | timestamp | |

Agents are scoped to a project and never work across projects. Identity is determined by `project_id + worktree_path` — if a session registers with a known worktree path, it reconnects to the existing Worktree record.

### Session

Ephemeral record of a single Claude Code terminal run within a worktree.

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| worktree_id | FK → Worktree | Parent worktree |
| started_at | timestamp | |
| ended_at | timestamp | Nullable, set on unregister or heartbeat timeout |

### Document

Append-only audit trail. Stores the actual content of specs, plans, and design docs generated during brainstorming and agent work. Documents are write-once — never edited through the board.

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| type | enum | spec / plan / design / other |
| title | string | Document title |
| content | text | Full markdown content |
| source_path | string | Original file path inside VM (reference only) |
| attached_to_type | enum | epic / feature / task |
| attached_to_id | UUID | Polymorphic FK |
| created_at | timestamp | |

## API Design

Auth: `Authorization: Bearer <project-api-key>` header on all agent-facing endpoints.

### Agent-Facing Endpoints (Write Path)

```
POST   /api/v1/agents/register
       Body: { worktree_path }
       Returns: { worktree_id, name, current_task, resumed: bool }
       Upserts worktree, creates session.

POST   /api/v1/agents/{worktree_id}/heartbeat
       Periodic liveness ping. Updates last_heartbeat.

GET    /api/v1/agents/{worktree_id}/tasks
       Returns ordered list of tasks assigned to this worktree.

POST   /api/v1/agents/{worktree_id}/start-task
       Body: { task_id }
       Moves task to in_progress, sets worktree.current_task.

POST   /api/v1/agents/{worktree_id}/complete-task
       Body: { task_id }
       Moves task to done, clears current_task, returns next task if available.

PATCH  /api/v1/agents/{worktree_id}/task-status
       Body: { task_id, status }
       Move task to a specific column (e.g., review).

POST   /api/v1/agents/{worktree_id}/task-note
       Body: { task_id, note }
       Append a brief status note.

POST   /api/v1/agents/{worktree_id}/documents
       Body: { task_id, type, title, content, source_path }
       Attach a document to a task.

POST   /api/v1/agents/{worktree_id}/unregister
       Ends the current session, sets worktree to idle.
```

### Dashboard-Facing Endpoints (Read Path)

```
GET    /api/v1/projects
       List all projects with summary stats.

GET    /api/v1/projects/{id}
       Project detail.

GET    /api/v1/projects/{id}/board
       Full Kanban board: tasks grouped by column, with worktree and document info.

GET    /api/v1/projects/{id}/epics
       Epics with roll-up status.

GET    /api/v1/projects/{id}/epics/{id}/features
       Features under an epic with roll-up status.

GET    /api/v1/projects/{id}/worktrees
       Active worktrees and their current tasks.

GET    /api/v1/tasks/{id}/documents
       List documents attached to a task.

GET    /api/v1/documents/{id}
       Full document content.

GET    /api/v1/projects/{id}/stream
       SSE endpoint for real-time board updates.
```

### Management Endpoints (Your Actions)

```
POST   /api/v1/projects
       Create project, generates API key.
       Returns: { project, api_key } (key shown once, stored hashed)

POST   /api/v1/projects/{id}/epics
POST   /api/v1/projects/{id}/epics/{id}/features
POST   /api/v1/projects/{id}/features/{id}/tasks
       Create individual items.

POST   /api/v1/projects/{id}/import
       Bulk import epics/features/tasks from a structured plan.
       Body: { epics: [{ title, features: [{ title, tasks: [...] }] }] }
       This is the brainstorming → board bridge.

PATCH  /api/v1/tasks/{id}
       Edit task (reprioritize, reassign worktree, change status).

DELETE /api/v1/tasks/{id}
       Remove a task (quality gate).

POST   /api/v1/worktrees/{id}/assign
       Assign a specific task to a worktree.
```

### CLI Tool

A `cloglog` CLI on the host for quick management:

```bash
cloglog projects                          # List projects
cloglog board <project>                   # Show board in terminal
cloglog assign <project> <worktree> <task> # Assign task
cloglog import <project> <file.json>      # Import plan
cloglog worktrees <project>               # List worktrees
```

## MCP Server (cloglog-mcp)

Installed in the agent-vm base image during `agent-vm setup`. Configured in `~/.claude.json` inside the VM.

### Installation

Added to `agent-vm.setup.sh`:
```bash
npm install -g cloglog-mcp
```

Added to `~/.claude.json` inside the VM:
```json
{
  "mcpServers": {
    "cloglog": {
      "command": "cloglog-mcp",
      "env": {
        "CLOGLOG_URL": "${CLOGLOG_URL}",
        "CLOGLOG_API_KEY": "${CLOGLOG_API_KEY}"
      }
    }
  }
}
```

### Environment Variables

Set via `.agent-vm.runtime.sh` per project, or via `~/.agent-vm/runtime.sh` globally:

```bash
export CLOGLOG_URL="http://<host-ip>:8000"
export CLOGLOG_API_KEY="$(cat /credentials/cloglog-api-key)"
```

The API key file lives in `~/.agent-vm/credentials/cloglog-api-key` on the host, mounted read-only at `/credentials` inside the VM.

### MCP Tools

| Tool | Description |
|------|-------------|
| `register_agent` | Register this worktree with cloglog. Called at session start. Returns current task if resuming. |
| `get_my_tasks` | Get ordered list of assigned tasks. |
| `start_task` | Mark a task as In Progress. |
| `complete_task` | Mark task as Done, get next task. |
| `update_task_status` | Move task to a specific column. |
| `add_task_note` | Append a status note to current task. |
| `attach_document` | Read a local file and POST its content to cloglog as a document attachment. |
| `unregister_agent` | Sign off cleanly when session ends. |

### Agent Instructions (CLAUDE.md)

Each project's CLAUDE.md includes:

```markdown
## Task Management

You have cloglog tools for task management. Follow this workflow:

1. At session start, call `register_agent` to identify yourself.
2. Call `get_my_tasks` to see your assigned work.
3. Before starting work, call `start_task` with the task ID.
4. When you generate specs, plans, or design docs, call `attach_document` to record them.
5. When done with a task, call `complete_task` — it returns your next task.
6. If no more tasks, your work is done for this session.
```

## Frontend

### Tech Stack

- React (Vite)
- Dark and light themes (CSS variables, toggle in sidebar header)
- SSE for real-time updates from the backend

### Layout

Sidebar + Board (Layout A):

- **Sidebar**: Project list with status dots (active/idle pulse animation), agent roster showing worktrees for selected project with current task labels
- **Board header**: Project name, summary stats (total tasks, active worktrees, % done)
- **Kanban columns**: Backlog → Assigned → In Progress → Review → Done
- **Task cards**: Epic/feature breadcrumb, task title, document chips (spec/plan/design — colored, clickable), assigned worktree with status indicator
- **Card detail view**: Full task description, complete document list with content viewer, task history/notes, worktree assignment

### Design Language

- Typography: Bricolage Grotesque (display), DM Sans (body), IBM Plex Mono (technical/data)
- Dark theme: deep blue-black base (#06080d), cyan accent (#22d3ee), emerald active, amber working, purple review
- Light theme: warm whites, teal accent (#0891b2), adjusted contrast
- Active worktrees have pulse animations on status indicators
- Cards lift on hover with subtle shadow
- Document chips are color-coded by type

## agent-vm Integration Points

### Base Image Setup (`agent-vm.setup.sh`)

- Install `cloglog-mcp` npm package
- Configure `~/.claude.json` with the cloglog MCP server entry

### Credentials (`~/.agent-vm/credentials/`)

- `cloglog-api-key` — project API key, mounted read-only at `/credentials`

### Per-Project Runtime (`.agent-vm.runtime.sh`)

- Set `CLOGLOG_URL` environment variable pointing to the host
- Set `CLOGLOG_API_KEY` from the credentials mount
- Optionally set `CLOGLOG_PROJECT` if needed for identification

### Agent Workflow

1. `agent-vm claude` starts a VM and launches Claude Code
2. Runtime script sets cloglog environment variables
3. Claude Code loads cloglog-mcp from its MCP config
4. Agent calls `register_agent` — worktree identity established or resumed
5. Agent calls `get_my_tasks` — gets its task list
6. Agent works through tasks sequentially, reporting status via MCP tools
7. Agent attaches any generated documents (specs, plans, designs)
8. On session end (context full, task complete, or exit), agent calls `unregister_agent`
9. If restarted in the same worktree, `register_agent` reconnects to existing identity

## Task Board Population

### From Brainstorming

When you brainstorm a project (using this skill or similar), the resulting spec and implementation plan produce a structured breakdown of epics, features, and tasks. This breakdown is posted to cloglog via:

```
POST /api/v1/projects/{id}/import
```

The import creates all items on the board in `backlog` status. You review them on the dashboard, delete anything that's junk, reprioritize, and assign tasks to worktrees. Only then do agents start picking up work.

### From Agent Work

Agents may discover sub-tasks during implementation. They can call `add_task_note` to flag this, but they do not create new tasks on the board. Task creation is your prerogative as the quality gate.

## Heartbeat & Offline Detection

Worktrees send a heartbeat every 60 seconds via the MCP server. If no heartbeat is received for 3 minutes, the dashboard marks the worktree as offline. The task remains in its current column — it doesn't automatically revert to backlog.

This handles:
- Terminal crashes
- VM restarts
- Network interruptions

When the session restarts and calls `register_agent`, the worktree goes back to active with its task intact.

## Testing Strategy

### Principles

- **Test-first**: Write testable specs before implementation. Code must satisfy the specs.
- **Never assume it works**: Every layer must be verified with the appropriate level of testing.
- **User testing checkpoints**: At the end of each phase, stop and provide precise manual testing instructions.

### Test Layers

**Unit tests** — for all business logic in isolation:
- Status roll-up computation (task → feature → epic)
- API key hashing and validation
- Heartbeat timeout detection
- Task assignment rules (can't assign to offline worktree, can't assign already-assigned task)
- Import payload parsing and validation

**Integration tests** — for API endpoints against a real PostgreSQL database:
- Full CRUD lifecycle for projects, epics, features, tasks
- Agent registration, task pickup, status update, completion flow
- Bulk import endpoint with nested hierarchy
- SSE event delivery when task status changes
- API key auth (valid key, invalid key, wrong project key)
- Worktree reconnection after session restart

**MCP server tests** — for the cloglog-mcp tool layer:
- Each MCP tool correctly maps to the right API call
- File reading + content posting for `attach_document`
- Error handling when cloglog service is unreachable
- Heartbeat timer starts on register, stops on unregister

**Frontend tests** — for the React dashboard:
- Component rendering (board, cards, sidebar, document viewer)
- Real-time updates via SSE (mock SSE source, verify board re-renders)
- Theme switching
- Project selection and board loading

**End-to-end tests** — full stack verification per phase:
- Agent registers → picks task → updates status → completes task → dashboard reflects all changes
- Import plan → tasks appear on board → assign to worktree → agent picks up
- Document attachment from agent → visible on dashboard card

### User Testing Checkpoints

At the end of each phase, work stops and the user receives:
1. What was built in this phase
2. How to start the relevant services
3. Exact steps to test (URLs to visit, API calls to make, what to verify)
4. Expected outcomes for each step
5. Known limitations at this phase

## Implementation Phases

The project is built in vertical slices. Each phase delivers a working, testable increment. Phases are designed to maximize parallelism — multiple agents can work on independent components simultaneously within each phase.

### Phase 1: Foundation

Vertical slice: Create a project via API, see it in a minimal frontend.

| Agent | Work | Dependencies |
|-------|------|-------------|
| Agent A | Backend: FastAPI project scaffold, PostgreSQL setup, Project model + CRUD endpoints, API key generation | None |
| Agent B | Frontend: React + Vite scaffold, project list sidebar component (hardcoded data), dark/light theme system with CSS variables, typography setup | None |
| Agent C | cloglog-mcp: Node.js MCP server scaffold, `register_agent` tool stub that calls a URL | None |

**Integration point**: Once A and B are done, connect frontend to backend API. Once C is done, verify it can reach A's endpoints.

**User test**: Start backend, start frontend, create a project via CLI/curl, see it appear in the sidebar.

### Phase 2: Hierarchy & Board

Vertical slice: Import a plan with epics/features/tasks, see them on the Kanban board.

| Agent | Work | Dependencies |
|-------|------|-------------|
| Agent A | Backend: Epic, Feature, Task models, CRUD endpoints, `/import` bulk endpoint, status roll-up logic | Phase 1 backend |
| Agent B | Frontend: Kanban board component, task cards with epic/feature breadcrumb, column rendering, board header with stats | Phase 1 frontend |
| Agent C | CLI tool: `cloglog projects`, `cloglog import`, `cloglog board` commands | Phase 1 backend |

**Integration point**: Connect board to `/board` API endpoint. Test import → board render.

**User test**: Import a sample plan JSON, see epics/features/tasks appear on the board in correct columns. Verify stats are accurate.

### Phase 3: Agent Workflow

Vertical slice: Agent registers, picks up a task, updates status, completes it — all visible on the dashboard in real-time.

| Agent | Work | Dependencies |
|-------|------|-------------|
| Agent A | Backend: Worktree + Session models, agent-facing endpoints (register, heartbeat, start-task, complete-task, task-status), SSE stream | Phase 2 backend |
| Agent B | Frontend: Worktree roster in sidebar, live status indicators with pulse animations, SSE client for real-time updates, card agent assignment display | Phase 2 frontend |
| Agent C | cloglog-mcp: All MCP tools implemented (register, get_my_tasks, start_task, complete_task, update_task_status, unregister), heartbeat timer | Phase 1 MCP + Phase 2 backend |

**Integration point**: MCP server → backend → SSE → frontend. Full loop.

**User test**: Start backend + frontend. Use curl to simulate an agent registering, picking a task, moving it through columns. Verify real-time updates in the dashboard. Then test with actual cloglog-mcp if agent-vm integration is ready.

### Phase 4: Documents & Polish

Vertical slice: Agents attach documents, documents visible on card detail view. Task assignment from dashboard/CLI.

| Agent | Work | Dependencies |
|-------|------|-------------|
| Agent A | Backend: Document model, document endpoints (create, list, get), attach_document via agent API | Phase 3 backend |
| Agent B | Frontend: Document chips on cards, card detail view with document content renderer (markdown), document type filtering | Phase 3 frontend |
| Agent C | cloglog-mcp: `attach_document` tool (reads local file, posts content), `add_task_note` tool | Phase 3 MCP |
| Agent D | Backend + CLI: Task assignment endpoints, `cloglog assign` command, worktree assignment from dashboard UI | Phase 3 backend |

**Integration point**: Agent attaches doc → appears on dashboard card. Assign task via UI → agent picks it up.

**User test**: Full end-to-end flow. Import plan, assign tasks, simulate agent working through tasks with document attachments, verify everything on dashboard. Test card detail view with markdown rendering.

### Phase 5: agent-vm Integration

Vertical slice: Everything works inside actual agent-vm sandboxes.

| Agent | Work | Dependencies |
|-------|------|-------------|
| Agent A | agent-vm changes: Add cloglog-mcp to `agent-vm.setup.sh`, configure `~/.claude.json`, document credential setup | Phase 4 MCP |
| Agent B | CLAUDE.md template: Write standard cloglog instructions for project CLAUDE.md files, test that agents follow the workflow | Phase 4 all |

**User test**: Full real-world test. Create a project in cloglog, import a small plan, start `agent-vm claude` with cloglog configured, watch the agent register and work through tasks on the live dashboard.

## Constraints & Non-Goals

- **No cross-project agents**: Agents belong to exactly one project. Enforced by API key scoping.
- **No agent-to-agent communication**: Agents don't know about each other. Coordination is done by you through task assignment.
- **No document editing through the board**: Documents are append-only audit trail.
- **No mid-task interruption**: You don't push new work to a running agent session. Assign tasks before the session starts or between sessions.
- **No Claude Agent SDK**: Agents are Claude Code CLI sessions with `--dangerously-skip-permissions` inside agent-vm. Integration is via MCP tools, not SDK.
- **Agents don't create tasks**: Only you create tasks (directly or via import). Agents work on what's assigned.
