"""Integration tests for the Agent context API endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.repository import AgentRepository
from src.agent.services import AgentService
from src.board.models import Epic, Feature, Task
from src.board.repository import BoardRepository


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

        # Complete task — now blocked (agents can't mark done)
        resp = await client.post(
            f"/api/v1/agents/{wt_id}/complete-task",
            json={"task_id": task_id},
        )
        assert resp.status_code == 409
        assert "cannot mark tasks as done" in resp.json()["detail"].lower()

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

        # Update to review (pr_url now required for all task types)
        resp = await client.patch(
            f"/api/v1/agents/{wt_id}/task-status",
            json={
                "task_id": task_id,
                "status": "review",
                "pr_url": "https://github.com/test/repo/pull/1",
            },
        )
        assert resp.status_code == 204


class TestTransitionGuardsAPI:
    """Integration tests for transition guards (T-114)."""

    async def _setup(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> tuple[str, str, str, str]:
        """Create project, register agent, create two tasks."""
        project = await _create_project_via_api(client)
        h = _auth(project["api_key"])
        task1_id = await _create_task_via_db(db_session, project["id"])

        # Create a second task in the same feature
        result = await db_session.execute(select(Feature).limit(1))
        feature = result.scalar_one()
        task2 = Task(
            feature_id=feature.id,
            title="Second task",
            description="Another task",
            priority="normal",
            position=1,
            status="assigned",
        )
        db_session.add(task2)
        await db_session.commit()
        await db_session.refresh(task2)

        reg = await client.post(
            "/api/v1/agents/register",
            json={
                "worktree_path": f"/repo/wt-guard-{uuid.uuid4().hex[:6]}",
                "branch_name": "wt-guard",
            },
            headers=h,
        )
        wt_id = reg.json()["worktree_id"]

        # Assign both tasks to the worktree
        assign = {"worktree_id": wt_id, "status": "assigned"}
        await client.patch(f"/api/v1/tasks/{task1_id}", json=assign)
        await client.patch(f"/api/v1/tasks/{str(task2.id)}", json=assign)

        return wt_id, task1_id, str(task2.id), project["api_key"]

    async def test_start_task_blocked_when_active_task(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Starting a second task while first is in_progress returns 409."""
        wt_id, task1_id, task2_id, _ = await self._setup(client, db_session)

        # Start first task
        resp = await client.post(f"/api/v1/agents/{wt_id}/start-task", json={"task_id": task1_id})
        assert resp.status_code == 200

        # Try starting second — should be blocked
        resp = await client.post(f"/api/v1/agents/{wt_id}/start-task", json={"task_id": task2_id})
        assert resp.status_code == 409
        assert "already has active" in resp.json()["detail"]

    async def test_start_task_allowed_after_review_merged(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """After first task is done, agent can start a second task."""
        wt_id, task1_id, task2_id, _ = await self._setup(client, db_session)

        # Start and complete first task (simulate user marking done via board API)
        await client.post(f"/api/v1/agents/{wt_id}/start-task", json={"task_id": task1_id})
        await client.patch(f"/api/v1/tasks/{task1_id}", json={"status": "done"})

        # Start second task — should succeed
        resp = await client.post(f"/api/v1/agents/{wt_id}/start-task", json={"task_id": task2_id})
        assert resp.status_code == 200
        assert resp.json()["status"] == "in_progress"

    async def test_review_requires_pr_url(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Moving to review without pr_url returns 409."""
        project = await _create_project_via_api(client)
        h = _auth(project["api_key"])
        task_id = await _create_task_via_db(db_session, project["id"])

        reg = await client.post(
            "/api/v1/agents/register",
            json={
                "worktree_path": f"/repo/wt-prurl-{uuid.uuid4().hex[:6]}",
                "branch_name": "wt-prurl",
            },
            headers=h,
        )
        wt_id = reg.json()["worktree_id"]
        await client.post(f"/api/v1/agents/{wt_id}/start-task", json={"task_id": task_id})

        # Try to move to review without pr_url
        resp = await client.patch(
            f"/api/v1/agents/{wt_id}/task-status",
            json={"task_id": task_id, "status": "review"},
        )
        assert resp.status_code == 409
        assert "PR URL" in resp.json()["detail"]

    async def test_review_to_in_progress_allowed(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Agent can move task from review back to in_progress."""
        project = await _create_project_via_api(client)
        h = _auth(project["api_key"])
        task_id = await _create_task_via_db(db_session, project["id"])

        reg = await client.post(
            "/api/v1/agents/register",
            json={
                "worktree_path": f"/repo/wt-revip-{uuid.uuid4().hex[:6]}",
                "branch_name": "wt-revip",
            },
            headers=h,
        )
        wt_id = reg.json()["worktree_id"]
        await client.post(f"/api/v1/agents/{wt_id}/start-task", json={"task_id": task_id})

        # Move to review with PR URL
        resp = await client.patch(
            f"/api/v1/agents/{wt_id}/task-status",
            json={
                "task_id": task_id,
                "status": "review",
                "pr_url": "https://github.com/test/repo/pull/1",
            },
        )
        assert resp.status_code == 204

        # Move back to in_progress
        resp = await client.patch(
            f"/api/v1/agents/{wt_id}/task-status",
            json={"task_id": task_id, "status": "in_progress"},
        )
        assert resp.status_code == 204

    async def test_agent_cannot_move_to_done(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Agent moving task to done returns 409."""
        project = await _create_project_via_api(client)
        h = _auth(project["api_key"])
        task_id = await _create_task_via_db(db_session, project["id"])

        reg = await client.post(
            "/api/v1/agents/register",
            json={
                "worktree_path": f"/repo/wt-nodone-{uuid.uuid4().hex[:6]}",
                "branch_name": "wt-nodone",
            },
            headers=h,
        )
        wt_id = reg.json()["worktree_id"]
        await client.post(f"/api/v1/agents/{wt_id}/start-task", json={"task_id": task_id})

        resp = await client.patch(
            f"/api/v1/agents/{wt_id}/task-status",
            json={"task_id": task_id, "status": "done"},
        )
        assert resp.status_code == 409
        assert "cannot mark tasks as done" in resp.json()["detail"].lower()


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


class TestHeartbeatTimeoutAPI:
    async def test_timeout_sets_worktree_offline(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Register an agent, expire its heartbeat, run cleanup, verify offline via API."""
        project = await _create_project_via_api(client)
        h = _auth(project["api_key"])

        reg = await client.post(
            "/api/v1/agents/register",
            json={"worktree_path": "/repo/wt-stale", "branch_name": "wt-stale"},
            headers=h,
        )
        assert reg.status_code == 201
        wt_id = reg.json()["worktree_id"]

        # Manually expire the heartbeat in the DB
        repo = AgentRepository(db_session)
        session = await repo.get_active_session(uuid.UUID(wt_id))
        assert session is not None
        session.last_heartbeat = datetime.now(UTC) - timedelta(minutes=10)
        await db_session.commit()

        # Run the timeout check
        service = AgentService(repo, BoardRepository(db_session))
        affected = await service.check_heartbeat_timeouts()
        assert uuid.UUID(wt_id) in affected

        # Verify via API that the worktree is now offline
        resp = await client.get(f"/api/v1/projects/{project['id']}/worktrees")
        assert resp.status_code == 200
        worktrees = resp.json()
        assert len(worktrees) == 1
        assert worktrees[0]["id"] == wt_id
        assert worktrees[0]["status"] == "offline"

    async def test_timeout_does_not_affect_fresh_agents(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Agents with recent heartbeats are not cleaned up."""
        project = await _create_project_via_api(client)
        h = _auth(project["api_key"])

        reg = await client.post(
            "/api/v1/agents/register",
            json={"worktree_path": "/repo/wt-fresh", "branch_name": "wt-fresh"},
            headers=h,
        )
        assert reg.status_code == 201
        wt_id = reg.json()["worktree_id"]

        # Send a heartbeat to keep it fresh
        hb = await client.post(f"/api/v1/agents/{wt_id}/heartbeat")
        assert hb.status_code == 200

        # Run timeout check — should not affect this agent
        repo = AgentRepository(db_session)
        service = AgentService(repo, BoardRepository(db_session))
        affected = await service.check_heartbeat_timeouts()
        assert uuid.UUID(wt_id) not in affected

        # Verify still online
        resp = await client.get(f"/api/v1/projects/{project['id']}/worktrees")
        worktrees = resp.json()
        assert len(worktrees) == 1
        assert worktrees[0]["status"] == "online"

    async def test_timed_out_agent_can_re_register(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """After timeout, an agent can re-register and resume."""
        project = await _create_project_via_api(client)
        h = _auth(project["api_key"])

        reg = await client.post(
            "/api/v1/agents/register",
            json={"worktree_path": "/repo/wt-comeback", "branch_name": "wt-comeback"},
            headers=h,
        )
        wt_id = reg.json()["worktree_id"]

        # Expire and timeout
        repo = AgentRepository(db_session)
        session = await repo.get_active_session(uuid.UUID(wt_id))
        assert session is not None
        session.last_heartbeat = datetime.now(UTC) - timedelta(minutes=10)
        await db_session.commit()

        service = AgentService(repo, BoardRepository(db_session))
        await service.check_heartbeat_timeouts()

        # Re-register
        reg2 = await client.post(
            "/api/v1/agents/register",
            json={"worktree_path": "/repo/wt-comeback", "branch_name": "wt-comeback"},
            headers=h,
        )
        assert reg2.status_code == 201
        assert reg2.json()["resumed"] is True
        assert reg2.json()["worktree_id"] == wt_id

        # Verify back online
        resp = await client.get(f"/api/v1/projects/{project['id']}/worktrees")
        worktrees = resp.json()
        assert len(worktrees) == 1
        assert worktrees[0]["status"] == "online"


class TestAgentMessagingAPI:
    async def test_send_message_endpoint(self, client: AsyncClient) -> None:
        project = await _create_project_via_api(client)
        h = _auth(project["api_key"])

        reg = await client.post(
            "/api/v1/agents/register",
            json={"worktree_path": "/repo/wt-msg", "branch_name": "wt-msg"},
            headers=h,
        )
        wt_id = reg.json()["worktree_id"]

        resp = await client.post(
            f"/api/v1/agents/{wt_id}/message",
            json={"message": "please rebase", "sender": "main-agent"},
        )
        assert resp.status_code == 202
        assert resp.json()["status"] == "queued"

    async def test_send_message_unknown_agent(self, client: AsyncClient) -> None:
        fake_id = uuid.uuid4()
        resp = await client.post(
            f"/api/v1/agents/{fake_id}/message",
            json={"message": "hello", "sender": "system"},
        )
        assert resp.status_code == 404

    async def test_heartbeat_delivers_messages(self, client: AsyncClient) -> None:
        project = await _create_project_via_api(client)
        h = _auth(project["api_key"])

        reg = await client.post(
            "/api/v1/agents/register",
            json={"worktree_path": "/repo/wt-hb-msg", "branch_name": "wt-hb-msg"},
            headers=h,
        )
        wt_id = reg.json()["worktree_id"]

        # Send a message
        await client.post(
            f"/api/v1/agents/{wt_id}/message",
            json={"message": "rebase on main", "sender": "main-agent"},
        )

        # Heartbeat picks it up
        resp = await client.post(f"/api/v1/agents/{wt_id}/heartbeat")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["pending_messages"]) == 1
        assert "[main-agent] rebase on main" in data["pending_messages"][0]

    async def test_message_delivery_marks_delivered(self, client: AsyncClient) -> None:
        project = await _create_project_via_api(client)
        h = _auth(project["api_key"])

        reg = await client.post(
            "/api/v1/agents/register",
            json={"worktree_path": "/repo/wt-del-msg", "branch_name": "wt-del-msg"},
            headers=h,
        )
        wt_id = reg.json()["worktree_id"]

        # Send first message and drain via heartbeat
        await client.post(
            f"/api/v1/agents/{wt_id}/message",
            json={"message": "old msg", "sender": "system"},
        )
        resp1 = await client.post(f"/api/v1/agents/{wt_id}/heartbeat")
        assert len(resp1.json()["pending_messages"]) == 1

        # Send a new message
        await client.post(
            f"/api/v1/agents/{wt_id}/message",
            json={"message": "new msg", "sender": "system"},
        )

        # Second heartbeat should only see the new message
        resp2 = await client.post(f"/api/v1/agents/{wt_id}/heartbeat")
        msgs = resp2.json()["pending_messages"]
        assert len(msgs) == 1
        assert "new msg" in msgs[0]
