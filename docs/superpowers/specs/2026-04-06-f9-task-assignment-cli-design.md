# Design Spec: F-9 Task Assignment CLI

**Feature:** F-9 Task Assignment CLI
**Date:** 2026-04-06
**Status:** Draft

## Problem

Agents and operators currently manage tasks exclusively through the MCP tools or raw HTTP API. There is no CLI for task operations — listing tasks, assigning them to worktrees, changing status, or filtering by feature/epic. The existing `cloglog` CLI (`src/gateway/cli.py`) only has `health`, `projects list`, and `projects create`.

A CLI enables:
- Operators to quickly inspect and manage tasks from the terminal
- Scripts (`create-worktree.sh`, `manage-worktrees.sh`) to assign tasks programmatically
- A consistent UX pattern alongside existing `cloglog projects` commands

## Design

### Command Structure

All task commands live under `cloglog tasks`:

```
cloglog tasks list      --project <name-or-id> [--status <status>] [--feature <id>] [--epic <id>] [--json]
cloglog tasks show      --task <number-or-id>   --project <name-or-id> [--json]
cloglog tasks assign    --task <number-or-id>   --project <name-or-id> --worktree <name-or-id>
cloglog tasks unassign  --task <number-or-id>   --project <name-or-id>
cloglog tasks start     --task <number-or-id>   --project <name-or-id>
cloglog tasks complete  --task <number-or-id>   --project <name-or-id>
cloglog tasks status    --task <number-or-id>   --project <name-or-id> --set <status>
```

### Addressing Tasks

Tasks can be addressed by:
- **Number** (e.g., `--task 101` or `--task T-101`) — human-friendly, resolved via the board API's search endpoint
- **UUID** — for programmatic use in scripts

The CLI tries number lookup first, falls back to UUID parsing.

### `tasks list`

Lists tasks grouped by status. Default output is a table:

```
$ cloglog tasks list --project cloglog

 In Progress (3)
  T-101  Write design spec for F-9           normal   wt-assign
  T-102  Write impl plan for F-9             normal   —
  T-103  Implement F-9                       normal   —

 Review (1)
  T-88   Add drag-drop to backlog            normal   wt-drag

 Backlog (12)
  T-30   Add cloglog tasks list command      normal   —
  ...

 Done (45)
  [hidden — use --status done to show]
```

Flags:
- `--status <status>` — filter to one status (backlog, in_progress, review, done)
- `--feature <number-or-id>` — filter to tasks under a specific feature
- `--epic <number-or-id>` — filter to tasks under a specific epic
- `--worktree <name>` — filter to tasks assigned to a specific worktree
- `--json` — output raw JSON array (for scripting)
- `--all` — include done tasks in table output (hidden by default)

### `tasks show`

Shows full detail for a single task:

```
$ cloglog tasks show --task T-101 --project cloglog

T-101: Write design spec for F-9 Task Assignment CLI
  Status:    in_progress
  Priority:  normal
  Feature:   F-9 Task Assignment CLI
  Epic:      E-3 Developer Experience
  Worktree:  wt-assign (9c3142d3...)
  Created:   2026-04-06 10:30:00
  Updated:   2026-04-06 11:15:00

  Description:
    Design the CLI commands for task assignment: cloglog tasks list,
    cloglog tasks assign, etc. Define command syntax, output formats,
    error handling. PR the spec for review.

  Notes (2):
    [2026-04-06 11:00] Test report: 3 new tests, all passing
    [2026-04-06 11:15] PR created: #42
```

With `--json`, returns the full task JSON from the API.

### `tasks assign`

Assigns a task to a worktree by setting `worktree_id` via `PATCH /tasks/{id}`:

```
$ cloglog tasks assign --task T-101 --project cloglog --worktree wt-assign
Assigned T-101 to worktree wt-assign
```

Resolves worktree name to UUID via `GET /projects/{id}/worktrees`.

**Errors:**
- Task not found → exit 1 with message
- Worktree not found → exit 1 with message
- Task already assigned → prints warning, proceeds (reassignment is valid)

### `tasks unassign`

Clears worktree assignment by setting `worktree_id` to null:

```
$ cloglog tasks unassign --task T-101 --project cloglog
Unassigned T-101 (was wt-assign)
```

### `tasks start`

Sets task status to `in_progress`:

```
$ cloglog tasks start --task T-101 --project cloglog
T-101 → in_progress
```

### `tasks complete`

Sets task status to `done`:

```
$ cloglog tasks complete --task T-101 --project cloglog
T-101 → done
```

### `tasks status`

Sets task status to any valid value:

```
$ cloglog tasks status --task T-101 --project cloglog --set review
T-101 → review
```

Valid statuses: `backlog`, `in_progress`, `review`, `done`.

### Common Options

All commands accept:
- `--url` — server base URL (default: `http://localhost:8000`, env: `CLOGLOG_URL`)
- `--api-key` — project API key (env: `CLOGLOG_API_KEY`)
- `--project` — project name or UUID (required for most commands)

### Project Resolution

`--project` accepts a name or UUID. The CLI resolves names by listing projects and matching. For frequently-used projects, `CLOGLOG_PROJECT` env var can be set to avoid repeating `--project`.

### Authentication

Task read operations (list, show) hit the board API which is public (no auth required for the dashboard). Task write operations (assign, start, complete, status) use `PATCH /tasks/{id}` which is also on the board router (public).

The `--api-key` flag is included for future auth requirements but not enforced for board routes today.

## Backend Changes

### New Endpoints

No new backend endpoints needed. The CLI composes existing endpoints:

| CLI Command | Backend Endpoint |
|---|---|
| `tasks list` | `GET /projects/{id}/backlog` (parses epic > feature > task tree) |
| `tasks show` | `GET /projects/{id}/backlog` + `GET /tasks/{id}/notes` |
| `tasks assign` | `PATCH /tasks/{id}` with `{"worktree_id": "<uuid>"}` |
| `tasks unassign` | `PATCH /tasks/{id}` with `{"worktree_id": null}` |
| `tasks start` | `PATCH /tasks/{id}` with `{"status": "in_progress"}` |
| `tasks complete` | `PATCH /tasks/{id}` with `{"status": "done"}` |
| `tasks status` | `PATCH /tasks/{id}` with `{"status": "<value>"}` |

### Task Lookup by Number

The existing `GET /projects/{id}/search?q=T-101` endpoint returns tasks by number. The CLI uses this to resolve task numbers to UUIDs.

### Worktree Lookup by Name

The existing `GET /projects/{id}/worktrees` endpoint returns all worktrees. The CLI matches by path suffix (the worktree name is the last path segment, e.g., `wt-assign`).

## Implementation in `src/gateway/cli.py`

```python
# New Typer sub-app, following existing pattern
tasks_app = typer.Typer(name="tasks", help="Manage tasks.")
app.add_typer(tasks_app)
```

### Helper Functions

- `_resolve_project(url, name_or_id)` — resolve project name to UUID
- `_resolve_task(url, project_id, number_or_id)` — resolve T-number to UUID via search
- `_resolve_worktree(url, project_id, name)` — resolve worktree name to UUID
- `_api_get(url, path)` / `_api_patch(url, path, json)` — HTTP helpers with error handling

### Output Formatting

Table output uses simple aligned columns (no external dependency). The `--json` flag outputs `json.dumps()` for piping.

## Testing Strategy

### Unit Tests (in `tests/gateway/test_cli.py`)

1. **Command existence** — each subcommand exists and accepts its flags (no exit code 2)
2. **Task number resolution** — `_resolve_task` correctly parses `T-101`, `101`, and UUIDs
3. **Project resolution** — `_resolve_project` finds by name and UUID
4. **JSON output** — `--json` flag produces valid JSON
5. **Error handling** — connection errors produce clean messages (exit 1, not tracebacks)

### Integration Tests (mock HTTP)

Use `httpx_mock` or `respx` to mock the backend and test full command flows:
- `tasks list` with various filters
- `tasks assign` success and error cases
- `tasks show` with notes

## File Changes

| File | Change |
|---|---|
| `src/gateway/cli.py` | Add `tasks` sub-app with all commands |
| `tests/gateway/test_cli.py` | Add tests for all task commands |

No model changes, no migrations, no new dependencies (httpx and typer are already installed).

## Out of Scope

- Interactive task creation (use MCP tools or the dashboard)
- Bulk operations (assign multiple tasks at once)
- Tab completion for task numbers (future enhancement)
- Color output (keep it simple for now; can add later with `rich`)
