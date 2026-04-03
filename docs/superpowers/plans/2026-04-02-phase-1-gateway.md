# Phase 1: Gateway Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Gateway context — API key auth middleware, route composition from all contexts, SSE fan-out endpoint, and CLI scaffold (`cloglog` commands).

**Architecture:** Gateway owns no tables. It composes routes from Board/Agent/Document contexts, adds auth middleware, and provides SSE streaming + CLI. Auth validates `Authorization: Bearer <api-key>` against Board's API key hashes.

**Tech Stack:** Python 3.12, FastAPI, Typer (CLI), sse-starlette, pytest

**Worktree:** `wt-gateway` — only touch `src/gateway/`, `tests/gateway/`

**Dependency:** Board context must be merged first (provides `BoardService.verify_api_key` and routes). If Board isn't merged yet, develop against the interface and mock it in tests.

---

## File Structure

| File | Responsibility |
|------|---------------|
| `src/gateway/app.py` | Already exists — add route composition, auth dependency |
| `src/gateway/auth.py` | API key auth middleware (FastAPI dependency) |
| `src/gateway/sse.py` | SSE endpoint using sse-starlette + EventBus |
| `src/gateway/cli.py` | Typer CLI: `cloglog projects`, `cloglog board`, `cloglog import` |
| `tests/gateway/test_auth.py` | Auth middleware tests (valid/invalid/missing key) |
| `tests/gateway/test_sse.py` | SSE endpoint tests |
| `tests/gateway/test_cli.py` | CLI command tests |

---

### Task 1: Auth Middleware

**Files:**
- Create: `src/gateway/auth.py`
- Test: `tests/gateway/test_auth.py`

- [ ] **Step 1: Write auth tests**

```python
# tests/gateway/test_auth.py
import pytest
from httpx import AsyncClient


@pytest.fixture
async def project_with_key(client: AsyncClient) -> dict:
    """Create a project and return {id, api_key}."""
    resp = await client.post("/api/v1/projects", json={"name": "auth-test-project"})
    data = resp.json()
    return {"id": data["id"], "api_key": data["api_key"]}


async def test_auth_valid_key(client: AsyncClient, project_with_key: dict):
    """Authenticated endpoint works with valid API key."""
    resp = await client.get(
        f"/api/v1/projects/{project_with_key['id']}/board",
        headers={"Authorization": f"Bearer {project_with_key['api_key']}"},
    )
    assert resp.status_code == 200


async def test_auth_missing_header(client: AsyncClient, project_with_key: dict):
    """Protected endpoint rejects requests without auth header."""
    resp = await client.get(
        f"/api/v1/authed/projects/{project_with_key['id']}/board",
    )
    assert resp.status_code == 401
    assert "Missing" in resp.json()["detail"] or "missing" in resp.json()["detail"].lower()


async def test_auth_invalid_key(client: AsyncClient, project_with_key: dict):
    """Protected endpoint rejects bad API key."""
    resp = await client.get(
        f"/api/v1/authed/projects/{project_with_key['id']}/board",
        headers={"Authorization": "Bearer bad-key-value"},
    )
    assert resp.status_code == 401


async def test_auth_wrong_bearer_format(client: AsyncClient):
    """Rejects auth header without Bearer prefix."""
    resp = await client.get(
        "/api/v1/authed/projects/00000000-0000-0000-0000-000000000000/board",
        headers={"Authorization": "Token some-key"},
    )
    assert resp.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test-gateway`
Expected: ImportError or 404 — auth module and authed routes don't exist yet.

- [ ] **Step 3: Implement auth middleware**

```python
# src/gateway/auth.py
"""API key authentication for agent-facing endpoints."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.board.repository import BoardRepository
from src.board.services import BoardService
from src.shared.database import get_session


async def require_api_key(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> BoardService:
    """FastAPI dependency that validates the Bearer API key.

    Returns the BoardService with the verified project context.
    Raises 401 if the key is missing, malformed, or invalid.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization format")

    api_key = auth_header[7:]  # Strip "Bearer "
    service = BoardService(BoardRepository(session))
    project = await service.verify_api_key(api_key)
    if project is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Store verified project on request state for downstream use
    request.state.project = project
    return service
```

- [ ] **Step 4: Add authed routes to app.py**

Update `src/gateway/app.py` to add a protected router group that requires auth:

```python
# src/gateway/app.py
"""FastAPI application factory.

Composes routes from all bounded contexts into a single app.
"""

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from src.gateway.auth import require_api_key


def create_app() -> FastAPI:
    app = FastAPI(
        title="cloglog",
        description="Multi-project Kanban dashboard for managing autonomous AI coding agents",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # Public routes (dashboard-facing, no auth required)
    from src.board.routes import router as board_router

    app.include_router(board_router, prefix="/api/v1")

    # Authed routes (agent-facing, require API key)
    authed = APIRouter(prefix="/api/v1/authed", dependencies=[Depends(require_api_key)])

    # Agent-facing board routes will be added here when agent context merges
    # For now, expose the board read endpoint as a test of auth
    @authed.get("/projects/{project_id}/board")
    async def authed_board(project_id: str, request: Request) -> dict:
        """Placeholder authed endpoint for testing auth middleware."""
        return {"project_id": project_id, "authed": True}

    app.include_router(authed)

    return app
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `make test-gateway`
Expected: All auth tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/gateway/auth.py src/gateway/app.py tests/gateway/test_auth.py
git commit -m "feat(gateway): add API key auth middleware"
```

---

### Task 2: SSE Endpoint

**Files:**
- Create: `src/gateway/sse.py`
- Test: `tests/gateway/test_sse.py`

- [ ] **Step 1: Write SSE tests**

```python
# tests/gateway/test_sse.py
import asyncio

import pytest
from httpx import AsyncClient

from src.shared.events import Event, EventType, event_bus


async def test_sse_stream_receives_event(client: AsyncClient):
    """SSE endpoint streams events for a project."""
    # Create a project to get a valid ID
    resp = await client.post("/api/v1/projects", json={"name": "sse-test"})
    project_id = resp.json()["id"]

    # Start listening to SSE in background
    events_received: list[str] = []

    async def listen():
        async with client.stream("GET", f"/api/v1/projects/{project_id}/stream") as response:
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    events_received.append(line)
                    break  # Got one event, stop

    listen_task = asyncio.create_task(listen())

    # Give the listener time to connect
    await asyncio.sleep(0.1)

    # Publish an event
    from uuid import UUID
    await event_bus.publish(Event(
        type=EventType.TASK_STATUS_CHANGED,
        project_id=UUID(project_id),
        data={"task_id": "test", "status": "in_progress"},
    ))

    # Wait for listener to receive it
    try:
        await asyncio.wait_for(listen_task, timeout=2.0)
    except asyncio.TimeoutError:
        pytest.fail("SSE listener did not receive event within timeout")

    assert len(events_received) == 1
    assert "task_status_changed" in events_received[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `make test-gateway`
Expected: Fails — SSE endpoint doesn't exist.

- [ ] **Step 3: Implement SSE endpoint**

```python
# src/gateway/sse.py
"""Server-Sent Events endpoint for real-time dashboard updates."""

from __future__ import annotations

import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from src.shared.events import Event, event_bus

router = APIRouter()


async def _event_generator(project_id: UUID, request: Request):
    queue = event_bus.subscribe(project_id)
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                event: Event = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield {
                    "event": event.type.value,
                    "data": json.dumps(event.data),
                }
            except asyncio.TimeoutError:
                # Send keepalive comment
                yield {"comment": "keepalive"}
    finally:
        event_bus.unsubscribe(project_id, queue)


@router.get("/projects/{project_id}/stream")
async def stream_events(project_id: UUID, request: Request):
    return EventSourceResponse(_event_generator(project_id, request))
```

- [ ] **Step 4: Register SSE router in app.py**

Add to `src/gateway/app.py` after the board router:

```python
    from src.gateway.sse import router as sse_router
    app.include_router(sse_router, prefix="/api/v1")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `make test-gateway`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/gateway/sse.py tests/gateway/test_sse.py src/gateway/app.py
git commit -m "feat(gateway): add SSE endpoint for real-time project events"
```

---

### Task 3: CLI Scaffold

**Files:**
- Create: `src/gateway/cli.py`
- Test: `tests/gateway/test_cli.py`

- [ ] **Step 1: Write CLI tests**

```python
# tests/gateway/test_cli.py
from typer.testing import CliRunner

from src.gateway.cli import app

runner = CliRunner()


def test_projects_command():
    """CLI projects command runs without error."""
    result = runner.invoke(app, ["projects"])
    # When no server is running, it should show an error message, not crash
    assert result.exit_code == 0 or "Error" in result.stdout or "error" in result.stdout.lower()


def test_board_command_missing_project():
    """CLI board command requires a project argument."""
    result = runner.invoke(app, ["board"])
    assert result.exit_code != 0  # Missing required argument
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test-gateway`
Expected: ImportError — `src.gateway.cli` has no `app`.

- [ ] **Step 3: Implement CLI**

```python
# src/gateway/cli.py
"""cloglog CLI tool for quick management from the host terminal."""

from __future__ import annotations

import json
import sys

import httpx
import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(name="cloglog", help="Manage cloglog projects and boards.")
console = Console()

BASE_URL = "http://localhost:8000/api/v1"


def _get(path: str) -> dict | list | None:
    try:
        resp = httpx.get(f"{BASE_URL}{path}", timeout=5.0)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        console.print("[red]Error: Cannot connect to cloglog server[/red]")
        return None
    except httpx.HTTPStatusError as e:
        console.print(f"[red]Error: {e.response.status_code} {e.response.text}[/red]")
        return None


def _post(path: str, data: dict | None = None) -> dict | None:
    try:
        resp = httpx.post(f"{BASE_URL}{path}", json=data or {}, timeout=5.0)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        console.print("[red]Error: Cannot connect to cloglog server[/red]")
        return None
    except httpx.HTTPStatusError as e:
        console.print(f"[red]Error: {e.response.status_code} {e.response.text}[/red]")
        return None


@app.command()
def projects() -> None:
    """List all projects."""
    data = _get("/projects")
    if data is None:
        return

    table = Table(title="Projects")
    table.add_column("ID", style="dim")
    table.add_column("Name", style="bold")
    table.add_column("Status")
    table.add_column("Created")

    for p in data:
        table.add_row(p["id"], p["name"], p["status"], p["created_at"][:10])

    console.print(table)


@app.command()
def board(project: str) -> None:
    """Show Kanban board for a project (pass project ID)."""
    data = _get(f"/projects/{project}/board")
    if data is None:
        return

    console.print(f"\n[bold]{data['project_name']}[/bold]  "
                  f"{data['done_count']}/{data['total_tasks']} done\n")

    for col in data["columns"]:
        if col["tasks"]:
            console.print(f"[bold cyan]── {col['status'].upper()} ({len(col['tasks'])}) ──[/bold cyan]")
            for task in col["tasks"]:
                prefix = "[dim]"
                if col["status"] == "in_progress":
                    prefix = "[yellow]"
                elif col["status"] == "done":
                    prefix = "[green]"
                console.print(f"  {prefix}{task['title']}[/] [dim]({task['id'][:8]})[/dim]")


@app.command(name="import")
def import_plan(project: str, file: str) -> None:
    """Import a plan JSON file onto the board."""
    try:
        with open(file) as f:
            plan = json.load(f)
    except FileNotFoundError:
        console.print(f"[red]File not found: {file}[/red]")
        raise typer.Exit(code=1)
    except json.JSONDecodeError:
        console.print(f"[red]Invalid JSON: {file}[/red]")
        raise typer.Exit(code=1)

    data = _post(f"/projects/{project}/import", plan)
    if data:
        console.print(
            f"[green]Imported: {data['epics_created']} epics, "
            f"{data['features_created']} features, "
            f"{data['tasks_created']} tasks[/green]"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `make test-gateway`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/gateway/cli.py tests/gateway/test_cli.py
git commit -m "feat(gateway): add CLI scaffold — projects, board, import commands"
```

---

### Task 4: Delete Placeholder Test & Final Quality Gate

**Files:**
- Delete: `tests/gateway/test_placeholder.py` (if it exists)

- [ ] **Step 1: Remove placeholder test if present**

```bash
rm -f tests/gateway/test_placeholder.py
```

- [ ] **Step 2: Run full quality gate**

Run: `make quality`
Expected: All checks pass.

- [ ] **Step 3: Commit cleanup**

```bash
git add -A tests/gateway/
git commit -m "chore(gateway): remove placeholder test"
```
