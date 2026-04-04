"""E2E tests for the agent lifecycle.

Covers: registration, heartbeat, task assignment,
task start/complete, worktree listing, and unregistration.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


def _unique_name(prefix: str = "agent-e2e") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _auth(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


async def _setup_project_with_task(client: AsyncClient) -> tuple[dict, str]:
    """Create a project with one task, return (project_dict, task_id)."""
    project = (
        await client.post(
            "/api/v1/projects",
            json={"name": _unique_name(), "description": "agent test"},
        )
    ).json()
    pid = project["id"]

    epic = (await client.post(f"/api/v1/projects/{pid}/epics", json={"title": "Agent Epic"})).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{pid}/epics/{epic['id']}/features",
            json={"title": "Agent Feature"},
        )
    ).json()
    task = (
        await client.post(
            f"/api/v1/projects/{pid}/features/{feature['id']}/tasks",
            json={"title": "Implement auth", "priority": "high"},
        )
    ).json()

    return project, task["id"]


# ── Registration ─────────────────────────────────────────────


async def test_agent_register(client: AsyncClient) -> None:
    project, _ = await _setup_project_with_task(client)
    h = _auth(project["api_key"])

    resp = await client.post(
        "/api/v1/agents/register",
        json={"worktree_path": "/repo/wt-auth", "branch_name": "wt-auth"},
        headers=h,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "worktree_id" in data
    assert "session_id" in data
    assert data["resumed"] is False


async def test_agent_register_resumes_existing(client: AsyncClient) -> None:
    project, _ = await _setup_project_with_task(client)
    h = _auth(project["api_key"])
    wt_path = f"/repo/wt-resume-{uuid.uuid4().hex[:6]}"

    # First registration
    r1 = await client.post(
        "/api/v1/agents/register",
        json={"worktree_path": wt_path, "branch_name": "wt-resume"},
        headers=h,
    )
    assert r1.status_code == 201
    wt_id = r1.json()["worktree_id"]

    # Unregister
    await client.post(f"/api/v1/agents/{wt_id}/unregister")

    # Re-register same path
    r2 = await client.post(
        "/api/v1/agents/register",
        json={"worktree_path": wt_path, "branch_name": "wt-resume"},
        headers=h,
    )
    assert r2.status_code == 201
    assert r2.json()["worktree_id"] == wt_id
    assert r2.json()["resumed"] is True


# ── Heartbeat ────────────────────────────────────────────────


async def test_agent_heartbeat(client: AsyncClient) -> None:
    project, _ = await _setup_project_with_task(client)
    h = _auth(project["api_key"])

    reg = await client.post(
        "/api/v1/agents/register",
        json={"worktree_path": "/repo/wt-hb", "branch_name": "wt-hb"},
        headers=h,
    )
    wt_id = reg.json()["worktree_id"]

    resp = await client.post(f"/api/v1/agents/{wt_id}/heartbeat")
    assert resp.status_code == 200
    assert resp.json()["status"] in ("online", "ok")
    assert "last_heartbeat" in resp.json()


# ── Task operations ──────────────────────────────────────────


async def test_agent_list_tasks(client: AsyncClient) -> None:
    project, task_id = await _setup_project_with_task(client)
    h = _auth(project["api_key"])

    reg = await client.post(
        "/api/v1/agents/register",
        json={"worktree_path": "/repo/wt-list", "branch_name": "wt-list"},
        headers=h,
    )
    wt_id = reg.json()["worktree_id"]

    resp = await client.get(f"/api/v1/agents/{wt_id}/tasks")
    assert resp.status_code == 200
    tasks = resp.json()
    assert isinstance(tasks, list)


async def test_agent_start_and_complete_task(client: AsyncClient) -> None:
    project, task_id = await _setup_project_with_task(client)
    h = _auth(project["api_key"])

    reg = await client.post(
        "/api/v1/agents/register",
        json={"worktree_path": "/repo/wt-lifecycle", "branch_name": "wt-lifecycle"},
        headers=h,
    )
    wt_id = reg.json()["worktree_id"]

    # Assign task to worktree first
    await client.patch(
        f"/api/v1/tasks/{task_id}",
        json={"status": "assigned", "worktree_id": wt_id},
    )

    # Start task
    start_resp = await client.post(f"/api/v1/agents/{wt_id}/start-task", json={"task_id": task_id})
    assert start_resp.status_code == 200
    assert start_resp.json()["status"] == "in_progress"

    # Complete task
    complete_resp = await client.post(
        f"/api/v1/agents/{wt_id}/complete-task", json={"task_id": task_id}
    )
    assert complete_resp.status_code == 200
    assert complete_resp.json()["completed_task_id"] == task_id


async def test_agent_update_task_status(client: AsyncClient) -> None:
    project, task_id = await _setup_project_with_task(client)
    h = _auth(project["api_key"])

    reg = await client.post(
        "/api/v1/agents/register",
        json={"worktree_path": "/repo/wt-status", "branch_name": "wt-status"},
        headers=h,
    )
    wt_id = reg.json()["worktree_id"]

    # Assign task
    await client.patch(
        f"/api/v1/tasks/{task_id}",
        json={"status": "assigned", "worktree_id": wt_id},
    )

    resp = await client.patch(
        f"/api/v1/agents/{wt_id}/task-status",
        json={"task_id": task_id, "status": "review"},
    )
    assert resp.status_code == 204


# ── Worktree listing ─────────────────────────────────────────


async def test_list_project_worktrees(client: AsyncClient) -> None:
    project, _ = await _setup_project_with_task(client)
    h = _auth(project["api_key"])

    await client.post(
        "/api/v1/agents/register",
        json={"worktree_path": "/repo/wt-a", "branch_name": "wt-a"},
        headers=h,
    )
    await client.post(
        "/api/v1/agents/register",
        json={"worktree_path": "/repo/wt-b", "branch_name": "wt-b"},
        headers=h,
    )

    resp = await client.get(f"/api/v1/projects/{project['id']}/worktrees")
    assert resp.status_code == 200
    worktrees = resp.json()
    assert len(worktrees) >= 2
    paths = {wt["worktree_path"] for wt in worktrees}
    assert "/repo/wt-a" in paths
    assert "/repo/wt-b" in paths


# ── Unregister ───────────────────────────────────────────────


async def test_agent_unregister(client: AsyncClient) -> None:
    project, _ = await _setup_project_with_task(client)
    h = _auth(project["api_key"])

    reg = await client.post(
        "/api/v1/agents/register",
        json={"worktree_path": "/repo/wt-unreg", "branch_name": "wt-unreg"},
        headers=h,
    )
    wt_id = reg.json()["worktree_id"]

    resp = await client.post(f"/api/v1/agents/{wt_id}/unregister")
    assert resp.status_code == 204
