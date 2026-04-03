"""Integration tests for the Agent context API endpoints."""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.board.models import Epic, Feature, Task


async def _create_project_via_api(client: AsyncClient) -> dict:
    """Create a project through the API and return the response."""
    resp = await client.post(
        "/api/v1/projects",
        json={"name": f"test-{uuid.uuid4().hex[:8]}", "description": "Integration test"},
    )
    assert resp.status_code == 201
    return resp.json()


async def _create_task_via_db(db_session: AsyncSession, project_id: str) -> str:
    """Create a task chain in the DB and return the task ID."""
    pid = uuid.UUID(project_id)
    epic = Epic(project_id=pid, title="Test Epic", position=0)
    db_session.add(epic)
    await db_session.commit()
    await db_session.refresh(epic)

    feature = Feature(epic_id=epic.id, title="Test Feature", position=0)
    db_session.add(feature)
    await db_session.commit()
    await db_session.refresh(feature)

    task = Task(
        feature_id=feature.id,
        title="Implement auth",
        description="Build OAuth flow",
        priority="high",
        position=0,
        status="assigned",
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    return str(task.id)


class TestAgentRegistrationAPI:
    async def test_register_new_agent(self, client: AsyncClient) -> None:
        project = await _create_project_via_api(client)

        resp = await client.post(
            f"/api/v1/agents/register?project_id={project['id']}",
            json={"worktree_path": "/repo/wt-auth", "branch_name": "wt-auth"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["resumed"] is False
        assert data["worktree_id"] is not None
        assert data["session_id"] is not None
        assert data["current_task"] is None

    async def test_register_reconnects(self, client: AsyncClient) -> None:
        project = await _create_project_via_api(client)

        r1 = await client.post(
            f"/api/v1/agents/register?project_id={project['id']}",
            json={"worktree_path": "/repo/wt-auth", "branch_name": "wt-auth"},
        )
        wt_id = r1.json()["worktree_id"]

        # Unregister
        await client.post(f"/api/v1/agents/{wt_id}/unregister")

        # Re-register
        r2 = await client.post(
            f"/api/v1/agents/register?project_id={project['id']}",
            json={"worktree_path": "/repo/wt-auth", "branch_name": "wt-auth"},
        )
        assert r2.status_code == 201
        assert r2.json()["resumed"] is True
        assert r2.json()["worktree_id"] == wt_id

    async def test_register_requires_project_id(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/agents/register",
            json={"worktree_path": "/repo/wt-auth"},
        )
        assert resp.status_code == 400


class TestHeartbeatAPI:
    async def test_heartbeat_success(self, client: AsyncClient) -> None:
        project = await _create_project_via_api(client)
        reg = await client.post(
            f"/api/v1/agents/register?project_id={project['id']}",
            json={"worktree_path": "/repo/wt-auth", "branch_name": "wt-auth"},
        )
        wt_id = reg.json()["worktree_id"]

        resp = await client.post(f"/api/v1/agents/{wt_id}/heartbeat")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_heartbeat_unknown_worktree(self, client: AsyncClient) -> None:
        fake_id = uuid.uuid4()
        resp = await client.post(f"/api/v1/agents/{fake_id}/heartbeat")
        assert resp.status_code == 404


class TestTaskLifecycleAPI:
    async def test_full_task_lifecycle(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """Full flow: register → start task → complete task."""
        project = await _create_project_via_api(client)
        task_id = await _create_task_via_db(db_session, project["id"])

        # Register
        reg = await client.post(
            f"/api/v1/agents/register?project_id={project['id']}",
            json={"worktree_path": "/repo/wt-auth", "branch_name": "wt-auth"},
        )
        wt_id = reg.json()["worktree_id"]

        # Assign task to worktree first
        await client.patch(
            f"/api/v1/tasks/{task_id}",
            json={"worktree_id": wt_id, "status": "assigned"},
        )

        # Get tasks
        resp = await client.get(f"/api/v1/agents/{wt_id}/tasks")
        assert resp.status_code == 200
        tasks = resp.json()
        assert len(tasks) == 1
        assert tasks[0]["id"] == task_id

        # Start task
        resp = await client.post(
            f"/api/v1/agents/{wt_id}/start-task",
            json={"task_id": task_id},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "in_progress"

        # Complete task
        resp = await client.post(
            f"/api/v1/agents/{wt_id}/complete-task",
            json={"task_id": task_id},
        )
        assert resp.status_code == 200
        assert resp.json()["completed_task_id"] == task_id

    async def test_update_task_status(self, client: AsyncClient, db_session: AsyncSession) -> None:
        project = await _create_project_via_api(client)
        task_id = await _create_task_via_db(db_session, project["id"])

        reg = await client.post(
            f"/api/v1/agents/register?project_id={project['id']}",
            json={"worktree_path": "/repo/wt-auth", "branch_name": "wt-auth"},
        )
        wt_id = reg.json()["worktree_id"]

        # Start task first
        await client.post(
            f"/api/v1/agents/{wt_id}/start-task",
            json={"task_id": task_id},
        )

        # Update to review
        resp = await client.patch(
            f"/api/v1/agents/{wt_id}/task-status",
            json={"task_id": task_id, "status": "review"},
        )
        assert resp.status_code == 204


class TestWorktreeListAPI:
    async def test_list_worktrees(self, client: AsyncClient) -> None:
        project = await _create_project_via_api(client)

        # Register two worktrees
        await client.post(
            f"/api/v1/agents/register?project_id={project['id']}",
            json={"worktree_path": "/repo/wt-auth", "branch_name": "wt-auth"},
        )
        await client.post(
            f"/api/v1/agents/register?project_id={project['id']}",
            json={"worktree_path": "/repo/wt-api", "branch_name": "wt-api"},
        )

        resp = await client.get(f"/api/v1/projects/{project['id']}/worktrees")
        assert resp.status_code == 200
        worktrees = resp.json()
        assert len(worktrees) == 2
        paths = {w["worktree_path"] for w in worktrees}
        assert paths == {"/repo/wt-auth", "/repo/wt-api"}


class TestUnregisterAPI:
    async def test_unregister(self, client: AsyncClient) -> None:
        project = await _create_project_via_api(client)

        reg = await client.post(
            f"/api/v1/agents/register?project_id={project['id']}",
            json={"worktree_path": "/repo/wt-auth", "branch_name": "wt-auth"},
        )
        wt_id = reg.json()["worktree_id"]

        resp = await client.post(f"/api/v1/agents/{wt_id}/unregister")
        assert resp.status_code == 204

        # Verify worktree is offline
        resp = await client.get(f"/api/v1/projects/{project['id']}/worktrees")
        worktrees = resp.json()
        assert len(worktrees) == 1
        assert worktrees[0]["status"] == "offline"
