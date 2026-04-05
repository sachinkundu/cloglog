"""Integration tests for the Agent context API endpoints."""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.board.models import Epic, Feature, Task


def _auth(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


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
        h = _auth(project["api_key"])

        resp = await client.post(
            "/api/v1/agents/register",
            json={"worktree_path": "/repo/wt-auth", "branch_name": "wt-auth"},
            headers=h,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["resumed"] is False
        assert data["worktree_id"] is not None
        assert data["session_id"] is not None
        assert data["current_task"] is None

    async def test_register_reconnects(self, client: AsyncClient) -> None:
        """After unregister (which deletes the record), re-registering creates a fresh worktree."""
        project = await _create_project_via_api(client)
        h = _auth(project["api_key"])

        r1 = await client.post(
            "/api/v1/agents/register",
            json={"worktree_path": "/repo/wt-auth", "branch_name": "wt-auth"},
            headers=h,
        )
        assert r1.status_code == 201

        wt_id = r1.json()["worktree_id"]

        # Unregister (now deletes the worktree record)
        unreg = await client.post(f"/api/v1/agents/{wt_id}/unregister")
        assert unreg.status_code == 204

        # Re-register — creates a brand-new worktree, not a resume
        r2 = await client.post(
            "/api/v1/agents/register",
            json={"worktree_path": "/repo/wt-auth", "branch_name": "wt-auth"},
            headers=h,
        )
        assert r2.status_code == 201
        assert r2.json()["resumed"] is False
        assert r2.json()["worktree_id"] is not None

    async def test_register_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/agents/register",
            json={"worktree_path": "/repo/wt-auth"},
        )
        assert resp.status_code == 401


class TestHeartbeatAPI:
    async def test_heartbeat_success(self, client: AsyncClient) -> None:
        project = await _create_project_via_api(client)
        h = _auth(project["api_key"])
        reg = await client.post(
            "/api/v1/agents/register",
            json={"worktree_path": "/repo/wt-auth", "branch_name": "wt-auth"},
            headers=h,
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
        h = _auth(project["api_key"])
        task_id = await _create_task_via_db(db_session, project["id"])

        # Register
        reg = await client.post(
            "/api/v1/agents/register",
            json={"worktree_path": "/repo/wt-auth", "branch_name": "wt-auth"},
            headers=h,
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
        h = _auth(project["api_key"])
        task_id = await _create_task_via_db(db_session, project["id"])

        reg = await client.post(
            "/api/v1/agents/register",
            json={"worktree_path": "/repo/wt-auth", "branch_name": "wt-auth"},
            headers=h,
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
        h = _auth(project["api_key"])

        # Register two worktrees
        await client.post(
            "/api/v1/agents/register",
            json={"worktree_path": "/repo/wt-auth", "branch_name": "wt-auth"},
            headers=h,
        )
        await client.post(
            "/api/v1/agents/register",
            json={"worktree_path": "/repo/wt-api", "branch_name": "wt-api"},
            headers=h,
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
        h = _auth(project["api_key"])

        reg = await client.post(
            "/api/v1/agents/register",
            json={"worktree_path": "/repo/wt-auth", "branch_name": "wt-auth"},
            headers=h,
        )
        wt_id = reg.json()["worktree_id"]

        resp = await client.post(f"/api/v1/agents/{wt_id}/unregister")
        assert resp.status_code == 204

        # Verify worktree record is deleted
        resp = await client.get(f"/api/v1/projects/{project['id']}/worktrees")
        worktrees = resp.json()
        assert len(worktrees) == 0

    async def test_unregister_deletes_worktree_record(self, client: AsyncClient) -> None:
        """Unregistering an agent deletes the worktree from the DB."""
        project = await _create_project_via_api(client)
        h = _auth(project["api_key"])

        resp = await client.post(
            "/api/v1/agents/register",
            json={"worktree_path": "/tmp/test-unreg-del", "branch_name": "wt-del"},
            headers=h,
        )
        assert resp.status_code == 201
        worktree_id = resp.json()["worktree_id"]

        resp = await client.post(f"/api/v1/agents/{worktree_id}/unregister")
        assert resp.status_code == 204

        resp = await client.get(f"/api/v1/projects/{project['id']}/worktrees")
        worktree_ids = [w["id"] for w in resp.json()]
        assert worktree_id not in worktree_ids

    async def test_unregister_by_path_not_found(self, client: AsyncClient) -> None:
        """Unregister-by-path returns 404 for unknown path."""
        project = await _create_project_via_api(client)
        h = _auth(project["api_key"])

        resp = await client.post(
            "/api/v1/agents/unregister-by-path",
            json={"worktree_path": "/tmp/nonexistent"},
            headers=h,
        )
        assert resp.status_code == 404

    async def test_unregister_by_path_success(self, client: AsyncClient) -> None:
        """Unregister-by-path deletes the worktree record for the given path."""
        project = await _create_project_via_api(client)
        h = _auth(project["api_key"])

        resp = await client.post(
            "/api/v1/agents/register",
            json={"worktree_path": "/tmp/test-by-path", "branch_name": "wt-by-path"},
            headers=h,
        )
        assert resp.status_code == 201

        resp = await client.post(
            "/api/v1/agents/unregister-by-path",
            json={"worktree_path": "/tmp/test-by-path"},
            headers=h,
        )
        assert resp.status_code == 204

        resp = await client.get(f"/api/v1/projects/{project['id']}/worktrees")
        assert len(resp.json()) == 0

    async def test_unregister_by_path_with_artifacts(self, client: AsyncClient) -> None:
        """Unregister-by-path accepts optional artifact paths."""
        project = await _create_project_via_api(client)
        h = _auth(project["api_key"])

        resp = await client.post(
            "/api/v1/agents/register",
            json={"worktree_path": "/tmp/test-artifacts", "branch_name": "wt-artifacts"},
            headers=h,
        )
        assert resp.status_code == 201

        resp = await client.post(
            "/api/v1/agents/unregister-by-path",
            json={
                "worktree_path": "/tmp/test-artifacts",
                "artifacts": {
                    "work_log": "/tmp/test-artifacts/WORK_LOG.md",
                    "learnings": "/tmp/test-artifacts/LEARNINGS.md",
                },
            },
            headers=h,
        )
        assert resp.status_code == 204

        resp = await client.get(f"/api/v1/projects/{project['id']}/worktrees")
        assert len(resp.json()) == 0
