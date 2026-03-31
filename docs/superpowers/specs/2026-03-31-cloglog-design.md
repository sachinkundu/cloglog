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

## Constraints & Non-Goals

- **No cross-project agents**: Agents belong to exactly one project. Enforced by API key scoping.
- **No agent-to-agent communication**: Agents don't know about each other. Coordination is done by you through task assignment.
- **No document editing through the board**: Documents are append-only audit trail.
- **No mid-task interruption**: You don't push new work to a running agent session. Assign tasks before the session starts or between sessions.
- **No Claude Agent SDK**: Agents are Claude Code CLI sessions with `--dangerously-skip-permissions` inside agent-vm. Integration is via MCP tools, not SDK.
- **Agents don't create tasks**: Only you create tasks (directly or via import). Agents work on what's assigned.
