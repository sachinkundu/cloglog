"""CLI for the human operator to observe and manage the cloglog board.

Agents use MCP tools, not this CLI. This is for the human to inspect
task status, assign work, and manage the board from the terminal.
"""

from __future__ import annotations

import json
import uuid as _uuid
from typing import Annotated, Any

import httpx
import typer

app = typer.Typer(name="cloglog", help="CLI for the cloglog Kanban dashboard.")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo("cloglog 0.1.0")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool, typer.Option("--version", callback=_version_callback, is_eager=True)
    ] = False,
) -> None:
    """cloglog — Multi-project Kanban dashboard for AI coding agents."""


@app.command()
def health(
    url: Annotated[
        str, typer.Option(help="Base URL of the cloglog server")
    ] = "http://localhost:8000",
) -> None:
    """Check server health."""
    try:
        resp = httpx.get(f"{url}/health", timeout=5.0)
        data = resp.json()
        typer.echo(f"Status: {data.get('status', 'unknown')}")
    except httpx.ConnectError:
        typer.echo(f"Error: cannot connect to {url}", err=True)
        raise typer.Exit(code=1) from None


# --- Projects subcommand ---

projects_app = typer.Typer(name="projects", help="Manage projects.")
app.add_typer(projects_app)


@projects_app.command("list")
def projects_list(
    url: Annotated[str, typer.Option(help="Base URL")] = "http://localhost:8000",
    api_key: Annotated[str, typer.Option(help="Project API key", envvar="CLOGLOG_API_KEY")] = "",
) -> None:
    """List all projects."""
    headers = {"X-API-Key": api_key} if api_key else {}
    try:
        resp = httpx.get(f"{url}/api/v1/projects", headers=headers, timeout=5.0)
        for project in resp.json():
            typer.echo(f"  {project['id']}  {project['name']}  [{project['status']}]")
    except httpx.ConnectError:
        typer.echo(f"Error: cannot connect to {url}", err=True)
        raise typer.Exit(code=1) from None


@projects_app.command("create")
def projects_create(
    name: Annotated[str, typer.Option(help="Project name")],
    url: Annotated[str, typer.Option(help="Base URL")] = "http://localhost:8000",
    description: Annotated[str, typer.Option(help="Project description")] = "",
) -> None:
    """Create a new project."""
    try:
        resp = httpx.post(
            f"{url}/api/v1/projects",
            json={"name": name, "description": description},
            timeout=5.0,
        )
        data = resp.json()
        typer.echo(f"Created project: {data['id']}")
        if "api_key" in data:
            typer.echo(f"API Key (save this!): {data['api_key']}")
    except httpx.ConnectError:
        typer.echo(f"Error: cannot connect to {url}", err=True)
        raise typer.Exit(code=1) from None


# --- Shared helpers ---


def _auth_headers(api_key: str) -> dict[str, str]:
    """Build auth headers from an API key (used as dashboard key).

    Returns the ``X-Dashboard-Key`` header when the key is non-empty;
    otherwise returns an empty dict. The gateway's
    ``ApiAccessControlMiddleware`` rejects empty-header requests with
    401 on all non-agent, non-``/health`` routes — callers that hit a
    route requiring auth should validate the key BEFORE the HTTP call
    via ``_require_dashboard_key`` so the user gets a clear local
    error instead of a cryptic remote 401.
    """
    if not api_key:
        return {}
    return {"X-Dashboard-Key": api_key}


def _require_dashboard_key(api_key: str, operation: str) -> None:
    """Exit with a clear error if the dashboard key is missing (T-258).

    Call this at the top of any CLI function that hits a non-agent route
    (e.g. ``/api/v1/projects/{id}/worktrees``). Before T-258, callers
    relied on implicit ``CLOGLOG_API_KEY`` env-passthrough through
    ``_auth_headers`` — unset env produced empty headers, which the
    middleware rejected with a bare ``401 Authentication required`` the
    user had to decode. This guard surfaces the requirement at the call
    site with a message that names the operation and the env var.
    """
    if not api_key:
        typer.echo(
            f"Error: {operation} requires the dashboard key. Set "
            "CLOGLOG_API_KEY in env or pass --api-key. The endpoint is "
            "NOT public — see docs/ddd-context-map.md § Auth Contract.",
            err=True,
        )
        raise typer.Exit(code=1)


def _api_get(url: str, path: str, api_key: str = "") -> dict[str, Any] | list[Any]:
    """GET with standard error handling."""
    try:
        resp = httpx.get(f"{url}{path}", headers=_auth_headers(api_key), timeout=5.0)
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]
    except httpx.ConnectError:
        typer.echo(f"Error: cannot connect to {url}", err=True)
        raise typer.Exit(code=1) from None
    except httpx.HTTPStatusError as exc:
        typer.echo(f"Error: {exc.response.status_code} {exc.response.text}", err=True)
        raise typer.Exit(code=1) from None


def _api_patch(url: str, path: str, json_body: dict[str, Any], api_key: str = "") -> dict[str, Any]:
    """PATCH with standard error handling."""
    try:
        resp = httpx.patch(
            f"{url}{path}", json=json_body, headers=_auth_headers(api_key), timeout=5.0
        )
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]
    except httpx.ConnectError:
        typer.echo(f"Error: cannot connect to {url}", err=True)
        raise typer.Exit(code=1) from None
    except httpx.HTTPStatusError as exc:
        typer.echo(f"Error: {exc.response.status_code} {exc.response.text}", err=True)
        raise typer.Exit(code=1) from None


def _resolve_project(url: str, name_or_id: str, api_key: str = "") -> tuple[str, str]:
    """Resolve project name or UUID to (id, name)."""
    try:
        _uuid.UUID(name_or_id)
        project = _api_get(url, f"/api/v1/projects/{name_or_id}", api_key=api_key)
        if isinstance(project, dict):
            return str(project["id"]), str(project["name"])
    except (ValueError, SystemExit):
        pass
    projects = _api_get(url, "/api/v1/projects", api_key=api_key)
    if isinstance(projects, list):
        for p in projects:
            if p["name"].lower() == name_or_id.lower():
                return str(p["id"]), str(p["name"])
    typer.echo(f"Error: project '{name_or_id}' not found", err=True)
    raise typer.Exit(code=1)


def _resolve_task(
    url: str, project_id: str, number_or_id: str, api_key: str = ""
) -> tuple[str, int, str]:
    """Resolve task T-number or UUID to (id, number, title)."""
    clean = number_or_id.lstrip("Tt-")
    if clean.isdigit():
        results = _api_get(
            url, f"/api/v1/projects/{project_id}/search?q=T-{clean}", api_key=api_key
        )
        if isinstance(results, dict):
            for r in results.get("results", []):
                if r["type"] == "task" and r["number"] == int(clean):
                    return str(r["id"]), int(r["number"]), str(r["title"])
    try:
        _uuid.UUID(number_or_id)
        backlog = _api_get(url, f"/api/v1/projects/{project_id}/backlog", api_key=api_key)
        if isinstance(backlog, list):
            for epic in backlog:
                for feat in epic["features"]:
                    for task in feat["tasks"]:
                        if task["id"] == number_or_id:
                            return str(task["id"]), int(task["number"]), str(task["title"])
    except ValueError:
        pass
    typer.echo(f"Error: task '{number_or_id}' not found", err=True)
    raise typer.Exit(code=1)


def _resolve_worktree(url: str, project_id: str, name: str, api_key: str = "") -> tuple[str, str]:
    """Resolve worktree name to (id, path).

    Hits ``/api/v1/projects/{id}/worktrees`` which is NOT a public route
    (see ``src/agent/routes.py::list_worktrees``). T-258 guards the
    dashboard-key requirement explicitly here instead of letting the
    ``_auth_headers`` fallback land an empty header on the wire.
    """
    _require_dashboard_key(api_key, "worktree resolution")
    worktrees = _api_get(url, f"/api/v1/projects/{project_id}/worktrees", api_key=api_key)
    if isinstance(worktrees, list):
        for wt in worktrees:
            path = wt.get("worktree_path", "")
            wt_name = path.rstrip("/").rsplit("/", 1)[-1] if path else ""
            if wt_name == name or str(wt.get("id", "")) == name:
                return str(wt["id"]), str(path)
    typer.echo(f"Error: worktree '{name}' not found", err=True)
    raise typer.Exit(code=1)


# --- Tasks subcommand ---

DISPLAY_ORDER = ["in_progress", "review", "backlog", "done"]
STATUS_LABELS = {
    "in_progress": "In Progress",
    "review": "Review",
    "backlog": "Backlog",
    "done": "Done",
}

tasks_app = typer.Typer(name="tasks", help="Inspect and manage tasks (for the human operator).")
app.add_typer(tasks_app)


def _flatten_backlog(backlog: list[Any]) -> list[dict[str, Any]]:
    """Flatten backlog tree into a flat list of task dicts with breadcrumbs."""
    tasks = []
    for epic in backlog:
        epic_info = epic["epic"]
        for feat in epic["features"]:
            feat_info = feat["feature"]
            for task in feat["tasks"]:
                tasks.append(
                    {
                        **task,
                        "epic_title": epic_info["title"],
                        "epic_number": epic_info["number"],
                        "feature_title": feat_info["title"],
                        "feature_number": feat_info["number"],
                    }
                )
    return tasks


@tasks_app.command("list")
def tasks_list(
    project: Annotated[str, typer.Option(help="Project name or UUID", envvar="CLOGLOG_PROJECT")],
    url: Annotated[
        str, typer.Option(help="Base URL", envvar="CLOGLOG_URL")
    ] = "http://localhost:8000",
    status: Annotated[str | None, typer.Option(help="Filter by status")] = None,
    epic: Annotated[str | None, typer.Option(help="Filter by epic number")] = None,
    feature: Annotated[str | None, typer.Option(help="Filter by feature number")] = None,
    worktree: Annotated[str | None, typer.Option(help="Filter by worktree name")] = None,
    all_tasks: Annotated[bool, typer.Option("--all", help="Include done tasks")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="JSON output")] = False,
    api_key: Annotated[str, typer.Option(help="Dashboard API key", envvar="CLOGLOG_API_KEY")] = "",
) -> None:
    """List tasks grouped by status.

    T-258 / codex round 1 correction: the dashboard key is required on
    EVERY invocation, not just when the ``--worktree`` filter is used.
    ``/api/v1/projects`` and ``/api/v1/projects/{id}/backlog`` are both
    non-agent routes and ``ApiAccessControlMiddleware`` rejects
    unauthenticated requests with 401 regardless of the filter flags.
    Guard the key up front so an unset ``CLOGLOG_API_KEY`` surfaces as a
    clear local error instead of a remote 401 from the first backend
    call. (The worktree filter hits an additional non-agent route
    ``/api/v1/projects/{id}/worktrees`` — still non-public — and is
    covered by the same guard.)
    """
    _require_dashboard_key(api_key, "tasks list")
    project_id, _ = _resolve_project(url, project, api_key=api_key)
    backlog = _api_get(url, f"/api/v1/projects/{project_id}/backlog", api_key=api_key)
    if not isinstance(backlog, list):
        typer.echo("Error: unexpected response", err=True)
        raise typer.Exit(code=1)

    tasks = _flatten_backlog(backlog)

    # Apply filters
    if status:
        tasks = [t for t in tasks if t["status"] == status]
    if epic:
        epic_num = int(epic.lstrip("Ee-")) if epic.lstrip("Ee-").isdigit() else None
        if epic_num is not None:
            tasks = [t for t in tasks if t["epic_number"] == epic_num]
    if feature:
        feat_num = int(feature.lstrip("Ff-")) if feature.lstrip("Ff-").isdigit() else None
        if feat_num is not None:
            tasks = [t for t in tasks if t["feature_number"] == feat_num]
    if worktree:
        wt_id, _ = _resolve_worktree(url, project_id, worktree, api_key=api_key)
        tasks = [t for t in tasks if t.get("worktree_id") == wt_id]

    if json_output:
        typer.echo(json.dumps(tasks, indent=2, default=str))
        return

    grouped: dict[str, list[dict[str, Any]]] = {s: [] for s in DISPLAY_ORDER}
    for t in tasks:
        s = t["status"]
        if s in grouped:
            grouped[s].append(t)

    for s in DISPLAY_ORDER:
        group = grouped[s]
        if not group:
            continue
        if s == "done" and not all_tasks and not status:
            typer.echo(f"\n {STATUS_LABELS[s]} ({len(group)})")
            typer.echo("  [hidden — use --all or --status done to show]")
            continue
        typer.echo(f"\n {STATUS_LABELS[s]} ({len(group)})")
        for t in group:
            num = f"T-{t['number']}"
            title = t["title"][:50]
            priority = t["priority"]
            typer.echo(f"  {num:<8} {title:<52} {priority}")


@tasks_app.command("show")
def tasks_show(
    task: Annotated[str, typer.Option(help="Task number (T-101) or UUID")],
    project: Annotated[str, typer.Option(help="Project name or UUID", envvar="CLOGLOG_PROJECT")],
    url: Annotated[
        str, typer.Option(help="Base URL", envvar="CLOGLOG_URL")
    ] = "http://localhost:8000",
    json_output: Annotated[bool, typer.Option("--json", help="JSON output")] = False,
) -> None:
    """Show detailed info for a single task."""
    project_id, _ = _resolve_project(url, project)
    task_id, task_num, task_title = _resolve_task(url, project_id, task)

    backlog = _api_get(url, f"/api/v1/projects/{project_id}/backlog")
    task_detail: dict[str, Any] | None = None
    if isinstance(backlog, list):
        for epic_entry in backlog:
            for feat in epic_entry["features"]:
                for t in feat["tasks"]:
                    if t["id"] == task_id:
                        task_detail = {
                            **t,
                            "epic_title": epic_entry["epic"]["title"],
                            "epic_number": epic_entry["epic"]["number"],
                            "feature_title": feat["feature"]["title"],
                            "feature_number": feat["feature"]["number"],
                        }
                        break

    if task_detail is None:
        typer.echo(f"Error: task T-{task_num} detail not found", err=True)
        raise typer.Exit(code=1)

    notes = _api_get(url, f"/api/v1/tasks/{task_id}/notes")

    if json_output:
        task_detail["notes"] = notes
        typer.echo(json.dumps(task_detail, indent=2, default=str))
        return

    typer.echo(f"\nT-{task_num}: {task_title}")
    typer.echo(f"  Status:    {task_detail['status']}")
    typer.echo(f"  Priority:  {task_detail['priority']}")
    typer.echo(f"  Feature:   F-{task_detail['feature_number']} {task_detail['feature_title']}")
    typer.echo(f"  Epic:      E-{task_detail['epic_number']} {task_detail['epic_title']}")
    if task_detail.get("worktree_id"):
        typer.echo(f"  Worktree:  {task_detail['worktree_id']}")

    if isinstance(notes, list) and notes:
        typer.echo(f"\n  Notes ({len(notes)}):")
        for n in notes:
            ts = str(n.get("created_at", ""))[:19]
            note_preview = str(n.get("note", ""))[:80]
            typer.echo(f"    [{ts}] {note_preview}")


@tasks_app.command("assign")
def tasks_assign(
    task: Annotated[str, typer.Option(help="Task number or UUID")],
    project: Annotated[str, typer.Option(help="Project name or UUID", envvar="CLOGLOG_PROJECT")],
    worktree: Annotated[str, typer.Option(help="Worktree name")],
    url: Annotated[
        str, typer.Option(help="Base URL", envvar="CLOGLOG_URL")
    ] = "http://localhost:8000",
    api_key: Annotated[str, typer.Option(help="Dashboard API key", envvar="CLOGLOG_API_KEY")] = "",
) -> None:
    """Assign a task to a worktree.

    T-258 / codex round 2: guard the dashboard key up front. Every step
    of this command hits a non-agent route — /api/v1/projects for the
    project resolver, /api/v1/projects/{id}/search for the task
    resolver, /api/v1/projects/{id}/worktrees for the worktree
    resolver, and /api/v1/tasks/{id} for the PATCH — and
    ApiAccessControlMiddleware rejects every one of them without the
    dashboard key. Guarding in `_resolve_worktree` only was too late:
    `_resolve_project` fires first and would still surface a remote 401.
    """
    _require_dashboard_key(api_key, "tasks assign")
    project_id, _ = _resolve_project(url, project, api_key=api_key)
    task_id, task_num, _ = _resolve_task(url, project_id, task, api_key=api_key)
    wt_id, _ = _resolve_worktree(url, project_id, worktree, api_key=api_key)
    _api_patch(url, f"/api/v1/tasks/{task_id}", {"worktree_id": wt_id}, api_key=api_key)
    typer.echo(f"Assigned T-{task_num} to worktree {worktree}")


@tasks_app.command("unassign")
def tasks_unassign(
    task: Annotated[str, typer.Option(help="Task number or UUID")],
    project: Annotated[str, typer.Option(help="Project name or UUID", envvar="CLOGLOG_PROJECT")],
    url: Annotated[
        str, typer.Option(help="Base URL", envvar="CLOGLOG_URL")
    ] = "http://localhost:8000",
) -> None:
    """Remove worktree assignment from a task."""
    project_id, _ = _resolve_project(url, project)
    task_id, task_num, _ = _resolve_task(url, project_id, task)
    _api_patch(url, f"/api/v1/tasks/{task_id}", {"worktree_id": None})
    typer.echo(f"Unassigned T-{task_num}")


@tasks_app.command("start")
def tasks_start(
    task: Annotated[str, typer.Option(help="Task number or UUID")],
    project: Annotated[str, typer.Option(help="Project name or UUID", envvar="CLOGLOG_PROJECT")],
    url: Annotated[
        str, typer.Option(help="Base URL", envvar="CLOGLOG_URL")
    ] = "http://localhost:8000",
) -> None:
    """Set task status to in_progress."""
    project_id, _ = _resolve_project(url, project)
    task_id, task_num, _ = _resolve_task(url, project_id, task)
    _api_patch(url, f"/api/v1/tasks/{task_id}", {"status": "in_progress"})
    typer.echo(f"T-{task_num} \u2192 in_progress")


@tasks_app.command("complete")
def tasks_complete(
    task: Annotated[str, typer.Option(help="Task number or UUID")],
    project: Annotated[str, typer.Option(help="Project name or UUID", envvar="CLOGLOG_PROJECT")],
    url: Annotated[
        str, typer.Option(help="Base URL", envvar="CLOGLOG_URL")
    ] = "http://localhost:8000",
) -> None:
    """Set task status to done."""
    project_id, _ = _resolve_project(url, project)
    task_id, task_num, _ = _resolve_task(url, project_id, task)
    _api_patch(url, f"/api/v1/tasks/{task_id}", {"status": "done"})
    typer.echo(f"T-{task_num} \u2192 done")


# --- Agents subcommand ---

agents_app = typer.Typer(name="agents", help="Inspect registered agents (worktrees).")
app.add_typer(agents_app)


@agents_app.command("list")
def agents_list(
    project: Annotated[str, typer.Option(help="Project name or UUID", envvar="CLOGLOG_PROJECT")],
    url: Annotated[
        str, typer.Option(help="Base URL", envvar="CLOGLOG_URL")
    ] = "http://localhost:8000",
    api_key: Annotated[str, typer.Option(help="Dashboard API key", envvar="CLOGLOG_API_KEY")] = "",
    status: Annotated[str | None, typer.Option(help="Filter by status")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="JSON output")] = False,
) -> None:
    """List registered agents (worktrees) for a project.

    T-258: ``/api/v1/projects/{id}/worktrees`` is NOT a public route;
    the dashboard key is required. Guard explicitly so users without
    ``CLOGLOG_API_KEY`` set get a clear local error naming the operation
    and env var, not a cryptic remote 401.
    """
    _require_dashboard_key(api_key, "agents list")
    project_id, project_name = _resolve_project(url, project, api_key=api_key)
    worktrees = _api_get(url, f"/api/v1/projects/{project_id}/worktrees", api_key=api_key)
    if not isinstance(worktrees, list):
        typer.echo("Error: unexpected response", err=True)
        raise typer.Exit(code=1)

    if status:
        worktrees = [wt for wt in worktrees if wt.get("status") == status]

    if json_output:
        typer.echo(json.dumps(worktrees, indent=2, default=str))
        return

    if not worktrees:
        typer.echo(f"No agents registered for project '{project_name}'.")
        return

    typer.echo(f"\nAgents for '{project_name}' ({len(worktrees)})\n")
    for wt in worktrees:
        name = wt.get("name", "unknown")
        wt_id = str(wt.get("id", ""))[:8]
        wt_status = wt.get("status", "unknown")
        branch = wt.get("branch_name", "")
        heartbeat = str(wt.get("last_heartbeat", "never"))[:19]
        current_task = wt.get("current_task_id")
        task_display = str(current_task)[:8] if current_task else "none"

        status_icon = "●" if wt_status == "active" else "○"
        typer.echo(f"  {status_icon} {name:<20} {wt_id}  {wt_status:<10} {branch}")
        typer.echo(f"    task: {task_display}  heartbeat: {heartbeat}")


@tasks_app.command("status")
def tasks_set_status(
    task: Annotated[str, typer.Option(help="Task number or UUID")],
    project: Annotated[str, typer.Option(help="Project name or UUID", envvar="CLOGLOG_PROJECT")],
    set_status: Annotated[str, typer.Option("--set", help="Target status")],
    url: Annotated[
        str, typer.Option(help="Base URL", envvar="CLOGLOG_URL")
    ] = "http://localhost:8000",
) -> None:
    """Set task status to any valid value."""
    valid = {"backlog", "in_progress", "review", "done"}
    if set_status not in valid:
        typer.echo(
            f"Error: invalid status '{set_status}'. Valid: {', '.join(sorted(valid))}",
            err=True,
        )
        raise typer.Exit(code=1)
    project_id, _ = _resolve_project(url, project)
    task_id, task_num, _ = _resolve_task(url, project_id, task)
    _api_patch(url, f"/api/v1/tasks/{task_id}", {"status": set_status})
    typer.echo(f"T-{task_num} \u2192 {set_status}")
