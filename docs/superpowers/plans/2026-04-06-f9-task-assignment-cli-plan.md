# Implementation Plan: F-9 Task Assignment CLI

**Feature:** F-9 Task Assignment CLI
**Spec:** `docs/superpowers/specs/2026-04-06-f9-task-assignment-cli-design.md`
**Date:** 2026-04-06

## Overview

Add `cloglog tasks` CLI subcommands (list, show, assign, unassign, start, complete, status) to `src/gateway/cli.py`. All commands compose existing backend API endpoints — no backend changes needed.

## Implementation Steps

### Step 1: Helper functions in cli.py

Add shared helper functions that all task commands depend on:

```python
# In src/gateway/cli.py

def _api_get(url: str, path: str) -> dict | list:
    """GET request with standard error handling."""
    resp = httpx.get(f"{url}{path}", timeout=5.0)
    resp.raise_for_status()
    return resp.json()

def _api_patch(url: str, path: str, json_body: dict) -> dict:
    """PATCH request with standard error handling."""
    resp = httpx.patch(f"{url}{path}", json=json_body, timeout=5.0)
    resp.raise_for_status()
    return resp.json()

def _resolve_project(url: str, name_or_id: str) -> tuple[str, str]:
    """Resolve project name or UUID to (id, name). Raises typer.Exit on failure."""
    # Try UUID first
    try:
        uuid.UUID(name_or_id)
        project = _api_get(url, f"/api/v1/projects/{name_or_id}")
        return project["id"], project["name"]
    except (ValueError, httpx.HTTPStatusError):
        pass
    # Try name match
    projects = _api_get(url, "/api/v1/projects")
    for p in projects:
        if p["name"].lower() == name_or_id.lower():
            return p["id"], p["name"]
    typer.echo(f"Error: project '{name_or_id}' not found", err=True)
    raise typer.Exit(code=1)

def _resolve_task(url: str, project_id: str, number_or_id: str) -> tuple[str, int, str]:
    """Resolve task T-number or UUID to (id, number, title). Raises typer.Exit on failure."""
    # Strip T- prefix if present
    clean = number_or_id.lstrip("Tt-")
    # Try as number via search
    if clean.isdigit():
        results = _api_get(url, f"/api/v1/projects/{project_id}/search?q=T-{clean}")
        for r in results.get("results", []):
            if r["type"] == "task" and r["number"] == int(clean):
                return r["id"], r["number"], r["title"]
    # Try as UUID
    try:
        uuid.UUID(number_or_id)
        # Look up in backlog to get number/title
        backlog = _api_get(url, f"/api/v1/projects/{project_id}/backlog")
        for epic in backlog:
            for feat in epic["features"]:
                for task in feat["tasks"]:
                    if task["id"] == number_or_id:
                        return task["id"], task["number"], task["title"]
    except ValueError:
        pass
    typer.echo(f"Error: task '{number_or_id}' not found", err=True)
    raise typer.Exit(code=1)

def _resolve_worktree(url: str, project_id: str, name: str) -> tuple[str, str]:
    """Resolve worktree name to (id, path). Raises typer.Exit on failure."""
    worktrees = _api_get(url, f"/api/v1/projects/{project_id}/worktrees")
    for wt in worktrees:
        path = wt.get("worktree_path", "")
        if path.rstrip("/").endswith(f"/{name}") or wt.get("id") == name:
            return wt["id"], path
    typer.echo(f"Error: worktree '{name}' not found", err=True)
    raise typer.Exit(code=1)
```

### Step 2: tasks list command

```python
tasks_app = typer.Typer(name="tasks", help="Manage tasks.")
app.add_typer(tasks_app)

@tasks_app.command("list")
def tasks_list(
    project: Annotated[str, typer.Option(help="Project name or UUID", envvar="CLOGLOG_PROJECT")],
    url: Annotated[str, typer.Option(help="Base URL", envvar="CLOGLOG_URL")] = "http://localhost:8000",
    status: Annotated[str | None, typer.Option(help="Filter by status")] = None,
    epic: Annotated[str | None, typer.Option(help="Filter by epic number")] = None,
    feature: Annotated[str | None, typer.Option(help="Filter by feature number")] = None,
    worktree: Annotated[str | None, typer.Option(help="Filter by worktree name")] = None,
    all_tasks: Annotated[bool, typer.Option("--all", help="Include done tasks")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="JSON output")] = False,
) -> None:
```

Fetches backlog, flattens tasks, groups by status, renders table or JSON.

### Step 3: tasks show command

```python
@tasks_app.command("show")
def tasks_show(
    task: Annotated[str, typer.Option(help="Task number (T-101) or UUID")],
    project: Annotated[str, typer.Option(help="Project name or UUID", envvar="CLOGLOG_PROJECT")],
    url: Annotated[str, typer.Option(help="Base URL", envvar="CLOGLOG_URL")] = "http://localhost:8000",
    json_output: Annotated[bool, typer.Option("--json", help="JSON output")] = False,
) -> None:
```

Resolves task, fetches full detail from backlog + notes endpoint, renders detail view.

### Step 4: tasks assign / unassign commands

```python
@tasks_app.command("assign")
def tasks_assign(
    task: Annotated[str, typer.Option(help="Task number or UUID")],
    project: Annotated[str, typer.Option(help="Project name or UUID", envvar="CLOGLOG_PROJECT")],
    worktree: Annotated[str, typer.Option(help="Worktree name")],
    url: Annotated[str, typer.Option(help="Base URL", envvar="CLOGLOG_URL")] = "http://localhost:8000",
) -> None:

@tasks_app.command("unassign")
def tasks_unassign(
    task: Annotated[str, typer.Option(help="Task number or UUID")],
    project: Annotated[str, typer.Option(help="Project name or UUID", envvar="CLOGLOG_PROJECT")],
    url: Annotated[str, typer.Option(help="Base URL", envvar="CLOGLOG_URL")] = "http://localhost:8000",
) -> None:
```

### Step 5: tasks start / complete / status commands

```python
@tasks_app.command("start")
def tasks_start(...) -> None:
    # PATCH /tasks/{id} with {"status": "in_progress"}

@tasks_app.command("complete")
def tasks_complete(...) -> None:
    # PATCH /tasks/{id} with {"status": "done"}

@tasks_app.command("status")
def tasks_set_status(
    task: ..., project: ..., set_status: Annotated[str, typer.Option("--set", help="Target status")], ...
) -> None:
    # PATCH /tasks/{id} with {"status": set_status}
```

### Step 6: Tests

Add to `tests/gateway/test_cli.py`:

**Unit tests (no HTTP):**
- Command existence for all 7 subcommands (verify exit code != 2)
- `_resolve_task` parsing: "T-101", "101", UUID string

**Integration tests (using `respx` to mock httpx):**
- `tasks list --project test` — mock backlog response, verify table output
- `tasks list --project test --json` — verify JSON output
- `tasks list --project test --status in_progress` — verify filter
- `tasks show --task T-101 --project test` — mock backlog + notes, verify detail
- `tasks assign --task T-101 --project test --worktree wt-assign` — mock search + worktrees + patch
- `tasks unassign --task T-101 --project test` — mock search + patch
- `tasks start --task T-101 --project test` — mock search + patch
- `tasks complete --task T-101 --project test` — mock search + patch
- `tasks status --task T-101 --project test --set review` — mock search + patch
- Error: unknown project → exit 1
- Error: unknown task → exit 1
- Error: connection refused → exit 1

**New dependency:** `respx` (dev dependency for mocking httpx in tests)

## Parallelism

Steps 1-5 are sequential (each builds on helpers). Step 6 (tests) can be parallelized with subagents:
- **Subagent A:** Write cli.py implementation (steps 1-5)
- **Subagent B:** Write test file (step 6) — can work from the spec since the function signatures are defined above

After both complete, run `make quality` to verify.

## Files Changed

| File | Change |
|---|---|
| `src/gateway/cli.py` | Add ~200 lines: helpers + 7 task commands |
| `tests/gateway/test_cli.py` | Add ~250 lines: unit + integration tests |
| `pyproject.toml` | Add `respx` to dev dependencies |

## Risks

- **respx compatibility**: Verify respx works with the installed httpx version (0.28+). If not, fall back to `unittest.mock.patch` on httpx.Client methods.
- **Search endpoint format**: The search endpoint returns `SearchResponse` with a `results` list. Verify the response shape matches what the CLI expects.
