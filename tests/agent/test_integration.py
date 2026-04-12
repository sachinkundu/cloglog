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


def _agent_auth(agent_token: str) -> dict[str, str]:
    """Auth headers for agent-scoped endpoints (uses agent token, not project API key)."""
    return {"Authorization": f"Bearer {agent_token}", "X-Dashboard-Key": ""}


async def _create_project_via_api(client: AsyncClient) -> dict:
    """Create a project through the API and return the response."""
    resp = await client.post(
        "/api/v1/projects",
        json={"name": f"test-{uuid.uuid4().hex[:8]}", "description": "Integration test"},
    )
    assert resp.status_code == 201
    return resp.json()


async def _register_and_get_token(
    client: AsyncClient,
    api_key: str,
    worktree_path: str,
    branch_name: str = "",
) -> tuple[str, str]:
    """Register agent and return (worktree_id, agent_token)."""
    branch = branch_name or worktree_path.split("/")[-1]
    resp = await client.post(
        "/api/v1/agents/register",
        json={"worktree_path": worktree_path, "branch_name": branch},
        headers=_auth(api_key),
    )
    assert resp.status_code == 201
    data = resp.json()
    return data["worktree_id"], data["agent_token"]


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
        agent_token = r1.json()["agent_token"]

        # Unregister (now deletes the worktree record)
        unreg = await client.post(
            f"/api/v1/agents/{wt_id}/unregister",
            headers=_agent_auth(agent_token),
        )
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
        agent_token = reg.json()["agent_token"]

        resp = await client.post(
            f"/api/v1/agents/{wt_id}/heartbeat",
            headers=_agent_auth(agent_token),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_heartbeat_unknown_worktree(self, client: AsyncClient) -> None:
        fake_id = uuid.uuid4()
        resp = await client.post(
            f"/api/v1/agents/{fake_id}/heartbeat",
            headers=_agent_auth("fake-token"),
        )
        assert resp.status_code == 401


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
        agent_token = reg.json()["agent_token"]
        ah = _agent_auth(agent_token)

        # Assign task to worktree first
        await client.patch(
            f"/api/v1/tasks/{task_id}",
            json={"worktree_id": wt_id, "status": "assigned"},
        )

        # Get tasks
        resp = await client.get(f"/api/v1/agents/{wt_id}/tasks", headers=ah)
        assert resp.status_code == 200
        tasks = resp.json()
        assert len(tasks) == 1
        assert tasks[0]["id"] == task_id

        # Start task
        resp = await client.post(
            f"/api/v1/agents/{wt_id}/start-task",
            json={"task_id": task_id},
            headers=ah,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "in_progress"

        # Complete task — now blocked (agents can't mark done)
        resp = await client.post(
            f"/api/v1/agents/{wt_id}/complete-task",
            json={"task_id": task_id},
            headers=ah,
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
        agent_token = reg.json()["agent_token"]
        ah = _agent_auth(agent_token)

        # Start task first
        await client.post(
            f"/api/v1/agents/{wt_id}/start-task",
            json={"task_id": task_id},
            headers=ah,
        )

        # Update to review (pr_url now required for all task types)
        resp = await client.patch(
            f"/api/v1/agents/{wt_id}/task-status",
            json={
                "task_id": task_id,
                "status": "review",
                "pr_url": "https://github.com/test/repo/pull/1",
            },
            headers=ah,
        )
        assert resp.status_code == 204


class TestTransitionGuardsAPI:
    """Integration tests for transition guards (T-114)."""

    async def _setup(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> tuple[str, str, str, str, str]:
        """Create project, register agent, create two tasks.

        Returns (wt_id, task1_id, task2_id, api_key, agent_token).
        """
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
        agent_token = reg.json()["agent_token"]

        # Assign both tasks to the worktree
        assign = {"worktree_id": wt_id, "status": "assigned"}
        await client.patch(f"/api/v1/tasks/{task1_id}", json=assign)
        await client.patch(f"/api/v1/tasks/{str(task2.id)}", json=assign)

        return wt_id, task1_id, str(task2.id), project["api_key"], agent_token

    async def test_start_task_blocked_when_active_task(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Starting a second task while first is in_progress returns 409."""
        wt_id, task1_id, task2_id, _, agent_token = await self._setup(client, db_session)
        ah = _agent_auth(agent_token)

        # Start first task
        resp = await client.post(
            f"/api/v1/agents/{wt_id}/start-task",
            json={"task_id": task1_id},
            headers=ah,
        )
        assert resp.status_code == 200

        # Try starting second — should be blocked
        resp = await client.post(
            f"/api/v1/agents/{wt_id}/start-task",
            json={"task_id": task2_id},
            headers=ah,
        )
        assert resp.status_code == 409
        assert "already has active" in resp.json()["detail"]

    async def test_start_task_allowed_after_review_merged(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """After first task is done, agent can start a second task."""
        wt_id, task1_id, task2_id, _, agent_token = await self._setup(client, db_session)
        ah = _agent_auth(agent_token)

        # Start and complete first task (simulate user marking done via board API)
        await client.post(
            f"/api/v1/agents/{wt_id}/start-task",
            json={"task_id": task1_id},
            headers=ah,
        )
        await client.patch(f"/api/v1/tasks/{task1_id}", json={"status": "done"})

        # Start second task — should succeed
        resp = await client.post(
            f"/api/v1/agents/{wt_id}/start-task",
            json={"task_id": task2_id},
            headers=ah,
        )
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
        agent_token = reg.json()["agent_token"]
        ah = _agent_auth(agent_token)
        await client.post(
            f"/api/v1/agents/{wt_id}/start-task",
            json={"task_id": task_id},
            headers=ah,
        )

        # Try to move to review without pr_url
        resp = await client.patch(
            f"/api/v1/agents/{wt_id}/task-status",
            json={"task_id": task_id, "status": "review"},
            headers=ah,
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
        agent_token = reg.json()["agent_token"]
        ah = _agent_auth(agent_token)
        await client.post(
            f"/api/v1/agents/{wt_id}/start-task",
            json={"task_id": task_id},
            headers=ah,
        )

        # Move to review with PR URL
        resp = await client.patch(
            f"/api/v1/agents/{wt_id}/task-status",
            json={
                "task_id": task_id,
                "status": "review",
                "pr_url": "https://github.com/test/repo/pull/1",
            },
            headers=ah,
        )
        assert resp.status_code == 204

        # Move back to in_progress
        resp = await client.patch(
            f"/api/v1/agents/{wt_id}/task-status",
            json={"task_id": task_id, "status": "in_progress"},
            headers=ah,
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
        agent_token = reg.json()["agent_token"]
        ah = _agent_auth(agent_token)
        await client.post(
            f"/api/v1/agents/{wt_id}/start-task",
            json={"task_id": task_id},
            headers=ah,
        )

        resp = await client.patch(
            f"/api/v1/agents/{wt_id}/task-status",
            json={"task_id": task_id, "status": "done"},
            headers=ah,
        )
        assert resp.status_code == 409
        assert "cannot mark tasks as done" in resp.json()["detail"].lower()


class TestPipelineOrderingAPI:
    """Integration tests for pipeline ordering guards (spec → plan → impl)."""

    async def _setup_pipeline(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ) -> tuple[str, str, str, str, str, str]:
        """Create project, agent, and spec/plan/impl tasks under one feature.
        Returns (wt_id, spec_id, plan_id, impl_id, api_key, agent_token)."""
        project = await _create_project_via_api(client)
        h = _auth(project["api_key"])
        pid = uuid.UUID(project["id"])

        epic = Epic(project_id=pid, title="Pipeline Epic", position=0)
        db_session.add(epic)
        await db_session.commit()
        await db_session.refresh(epic)

        feature = Feature(epic_id=epic.id, title="Pipeline Feature", position=0)
        db_session.add(feature)
        await db_session.commit()
        await db_session.refresh(feature)

        spec_task = Task(
            feature_id=feature.id,
            title="Write spec",
            description="Design spec",
            priority="high",
            position=0,
            status="assigned",
            task_type="spec",
        )
        plan_task = Task(
            feature_id=feature.id,
            title="Write plan",
            description="Impl plan",
            priority="high",
            position=1,
            status="assigned",
            task_type="plan",
        )
        impl_task = Task(
            feature_id=feature.id,
            title="Implement",
            description="Build it",
            priority="high",
            position=2,
            status="assigned",
            task_type="impl",
        )
        db_session.add_all([spec_task, plan_task, impl_task])
        await db_session.commit()
        for t in (spec_task, plan_task, impl_task):
            await db_session.refresh(t)

        reg = await client.post(
            "/api/v1/agents/register",
            json={
                "worktree_path": f"/repo/wt-pipe-{uuid.uuid4().hex[:6]}",
                "branch_name": "wt-pipe",
            },
            headers=h,
        )
        wt_id = reg.json()["worktree_id"]
        agent_token = reg.json()["agent_token"]

        # Assign all tasks to the worktree
        for t in (spec_task, plan_task, impl_task):
            await client.patch(
                f"/api/v1/tasks/{t.id}",
                json={"worktree_id": wt_id, "status": "assigned"},
            )

        return (
            wt_id,
            str(spec_task.id),
            str(plan_task.id),
            str(impl_task.id),
            project["api_key"],
            agent_token,
        )

    async def test_pipeline_ordering_spec_before_plan(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Starting plan task when spec is not done returns 409."""
        wt_id, spec_id, plan_id, _, _, agent_token = await self._setup_pipeline(client, db_session)
        ah = _agent_auth(agent_token)

        # Try to start plan without spec being done — should be blocked
        resp = await client.post(
            f"/api/v1/agents/{wt_id}/start-task",
            json={"task_id": plan_id},
            headers=ah,
        )
        assert resp.status_code == 409
        assert "spec" in resp.json()["detail"].lower()
        assert "not done" in resp.json()["detail"].lower()

    async def test_pipeline_ordering_plan_before_impl(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Starting impl task when plan is not done returns 409."""
        wt_id, spec_id, plan_id, impl_id, _, agent_token = await self._setup_pipeline(
            client, db_session
        )
        ah = _agent_auth(agent_token)

        # Complete spec (simulate user marking done via board API)
        await client.post(
            f"/api/v1/agents/{wt_id}/start-task",
            json={"task_id": spec_id},
            headers=ah,
        )
        await client.patch(f"/api/v1/tasks/{spec_id}", json={"status": "done"})

        # Try to start impl without plan being done — should be blocked
        resp = await client.post(
            f"/api/v1/agents/{wt_id}/start-task",
            json={"task_id": impl_id},
            headers=ah,
        )
        assert resp.status_code == 409
        assert "plan" in resp.json()["detail"].lower()
        assert "not done" in resp.json()["detail"].lower()

    async def test_pipeline_ordering_allows_after_predecessor_done(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Full pipeline: spec done -> plan starts, plan done -> impl starts."""
        wt_id, spec_id, plan_id, impl_id, _, agent_token = await self._setup_pipeline(
            client, db_session
        )
        ah = _agent_auth(agent_token)

        # Complete spec
        await client.post(
            f"/api/v1/agents/{wt_id}/start-task",
            json={"task_id": spec_id},
            headers=ah,
        )
        await client.patch(f"/api/v1/tasks/{spec_id}", json={"status": "done"})

        # Start plan — should succeed
        resp = await client.post(
            f"/api/v1/agents/{wt_id}/start-task",
            json={"task_id": plan_id},
            headers=ah,
        )
        assert resp.status_code == 200

        # Complete plan
        await client.patch(f"/api/v1/tasks/{plan_id}", json={"status": "done"})

        # Start impl — should succeed
        resp = await client.post(
            f"/api/v1/agents/{wt_id}/start-task",
            json={"task_id": impl_id},
            headers=ah,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "in_progress"


class TestAssignTaskAPI:
    async def test_assign_task_sets_worktree_id(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Assign a task to a worktree without changing its status."""
        project = await _create_project_via_api(client)
        h = _auth(project["api_key"])
        task_id = await _create_task_via_db(db_session, project["id"])

        reg = await client.post(
            "/api/v1/agents/register",
            json={"worktree_path": "/repo/wt-assign", "branch_name": "wt-assign"},
            headers=h,
        )
        wt_id = reg.json()["worktree_id"]
        agent_token = reg.json()["agent_token"]
        ah = _agent_auth(agent_token)

        resp = await client.patch(
            f"/api/v1/agents/{wt_id}/assign-task",
            json={"task_id": task_id},
            headers=ah,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == task_id
        assert data["worktree_id"] == wt_id
        assert data["status"] == "assigned"

        # Verify the task appears in get_my_tasks
        tasks_resp = await client.get(f"/api/v1/agents/{wt_id}/tasks", headers=ah)
        assert tasks_resp.status_code == 200
        tasks = tasks_resp.json()
        assert len(tasks) == 1
        assert tasks[0]["id"] == task_id
        # Status should be unchanged (still "assigned" from creation)
        assert tasks[0]["status"] == "assigned"

    async def test_assign_task_unknown_worktree(self, client: AsyncClient) -> None:
        fake_id = uuid.uuid4()
        resp = await client.patch(
            f"/api/v1/agents/{fake_id}/assign-task",
            json={"task_id": str(uuid.uuid4())},
            headers=_agent_auth("fake-token"),
        )
        assert resp.status_code == 401

    async def test_assign_task_unknown_task(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        project = await _create_project_via_api(client)
        h = _auth(project["api_key"])

        reg = await client.post(
            "/api/v1/agents/register",
            json={"worktree_path": "/repo/wt-assign-bad", "branch_name": "wt-assign-bad"},
            headers=h,
        )
        wt_id = reg.json()["worktree_id"]
        agent_token = reg.json()["agent_token"]

        resp = await client.patch(
            f"/api/v1/agents/{wt_id}/assign-task",
            json={"task_id": str(uuid.uuid4())},
            headers=_agent_auth(agent_token),
        )
        assert resp.status_code == 404


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
        agent_token = reg.json()["agent_token"]

        resp = await client.post(
            f"/api/v1/agents/{wt_id}/unregister",
            headers=_agent_auth(agent_token),
        )
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
        agent_token = resp.json()["agent_token"]

        resp = await client.post(
            f"/api/v1/agents/{worktree_id}/unregister",
            headers=_agent_auth(agent_token),
        )
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
        agent_token = reg.json()["agent_token"]

        # Send a heartbeat to keep it fresh
        hb = await client.post(
            f"/api/v1/agents/{wt_id}/heartbeat",
            headers=_agent_auth(agent_token),
        )
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


class TestReportArtifactAPI:
    async def test_report_artifact_success(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Report artifact on a spec task in review → 200 with artifact_path."""
        project = await _create_project_via_api(client)
        h = _auth(project["api_key"])
        pid = uuid.UUID(project["id"])

        epic = Epic(project_id=pid, title="Artifact Epic", position=0)
        db_session.add(epic)
        await db_session.commit()
        await db_session.refresh(epic)

        feature = Feature(epic_id=epic.id, title="Artifact Feature", position=0)
        db_session.add(feature)
        await db_session.commit()
        await db_session.refresh(feature)

        spec_task = Task(
            feature_id=feature.id,
            title="Write spec",
            description="Design spec",
            priority="high",
            position=0,
            status="assigned",
            task_type="spec",
        )
        db_session.add(spec_task)
        await db_session.commit()
        await db_session.refresh(spec_task)

        # Register agent
        reg = await client.post(
            "/api/v1/agents/register",
            json={
                "worktree_path": f"/repo/wt-art-{uuid.uuid4().hex[:6]}",
                "branch_name": "wt-art",
            },
            headers=h,
        )
        wt_id = reg.json()["worktree_id"]
        ah = _agent_auth(reg.json()["agent_token"])

        # Start the task
        start_resp = await client.post(
            f"/api/v1/agents/{wt_id}/start-task",
            json={"task_id": str(spec_task.id)},
            headers=ah,
        )
        assert start_resp.status_code == 200, f"start-task failed: {start_resp.status_code}"

        # Move to review with PR URL
        review_resp = await client.patch(
            f"/api/v1/agents/{wt_id}/task-status",
            json={
                "task_id": str(spec_task.id),
                "status": "review",
                "pr_url": "https://github.com/test/repo/pull/42",
            },
            headers=ah,
        )
        assert review_resp.status_code == 204, f"task-status failed: {review_resp.status_code}"

        # Report artifact
        resp = await client.post(
            f"/api/v1/agents/{wt_id}/report-artifact",
            json={
                "task_id": str(spec_task.id),
                "artifact_path": "docs/specs/my-spec.md",
            },
            headers=ah,
        )
        assert resp.status_code == 200, f"Expected 200 but got {resp.status_code}: {resp.json()}"
        data = resp.json()
        assert data["artifact_path"] == "docs/specs/my-spec.md"
        assert data["task_id"] == str(spec_task.id)

        # Verify artifact_path persisted in DB
        task_id = spec_task.id
        db_session.expire_all()
        board_repo = BoardRepository(db_session)
        refreshed = await board_repo.get_task(task_id)
        assert refreshed is not None
        assert refreshed.artifact_path == "docs/specs/my-spec.md"

    async def test_report_artifact_rejects_impl_task(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Report artifact on an impl task → 409 with 'only spec and plan'."""
        project = await _create_project_via_api(client)
        h = _auth(project["api_key"])
        pid = uuid.UUID(project["id"])

        epic = Epic(project_id=pid, title="Impl Epic", position=0)
        db_session.add(epic)
        await db_session.commit()
        await db_session.refresh(epic)

        feature = Feature(epic_id=epic.id, title="Impl Feature", position=0)
        db_session.add(feature)
        await db_session.commit()
        await db_session.refresh(feature)

        impl_task = Task(
            feature_id=feature.id,
            title="Implement it",
            description="Build it",
            priority="high",
            position=0,
            status="assigned",
            task_type="impl",
        )
        db_session.add(impl_task)
        await db_session.commit()
        await db_session.refresh(impl_task)

        # Register agent
        reg = await client.post(
            "/api/v1/agents/register",
            json={
                "worktree_path": f"/repo/wt-impl-art-{uuid.uuid4().hex[:6]}",
                "branch_name": "wt-impl-art",
            },
            headers=h,
        )
        wt_id = reg.json()["worktree_id"]
        ah = _agent_auth(reg.json()["agent_token"])

        # Start task, move to review
        await client.post(
            f"/api/v1/agents/{wt_id}/start-task",
            json={"task_id": str(impl_task.id)},
            headers=ah,
        )
        await client.patch(
            f"/api/v1/agents/{wt_id}/task-status",
            json={
                "task_id": str(impl_task.id),
                "status": "review",
                "pr_url": "https://github.com/test/repo/pull/99",
            },
            headers=ah,
        )

        # Try to report artifact on impl task
        resp = await client.post(
            f"/api/v1/agents/{wt_id}/report-artifact",
            json={
                "task_id": str(impl_task.id),
                "artifact_path": "docs/impl.md",
            },
            headers=ah,
        )
        assert resp.status_code == 409
        assert "only spec and plan" in resp.json()["detail"]


class TestBulkRemoveOfflineAgents:
    async def test_removes_offline_agents(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Bulk remove deletes offline agents and returns count."""
        project = await _create_project_via_api(client)
        api_key = project["api_key"]
        project_id = project["id"]

        # Register two agents
        wt1_id, _ = await _register_and_get_token(client, api_key, "/repo/wt-old1")
        wt2_id, _ = await _register_and_get_token(client, api_key, "/repo/wt-old2")

        # Mark both offline via repo
        repo = AgentRepository(db_session)
        await repo.set_worktree_offline(uuid.UUID(wt1_id))
        await repo.set_worktree_offline(uuid.UUID(wt2_id))

        # Bulk remove
        resp = await client.post(f"/api/v1/projects/{project_id}/worktrees/remove-offline")
        assert resp.status_code == 200
        assert resp.json() == {"removed_count": 2}

        # Verify no worktrees remain
        resp = await client.get(f"/api/v1/projects/{project_id}/worktrees")
        assert resp.json() == []

    async def test_does_not_remove_online_agents(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Bulk remove only removes offline agents, leaves online ones."""
        project = await _create_project_via_api(client)
        api_key = project["api_key"]
        project_id = project["id"]

        # Register two agents — one stays online, one goes offline
        wt_online_id, _ = await _register_and_get_token(client, api_key, "/repo/wt-online")
        wt_offline_id, _ = await _register_and_get_token(client, api_key, "/repo/wt-offline")

        repo = AgentRepository(db_session)
        await repo.set_worktree_offline(uuid.UUID(wt_offline_id))

        resp = await client.post(f"/api/v1/projects/{project_id}/worktrees/remove-offline")
        assert resp.status_code == 200
        assert resp.json() == {"removed_count": 1}

        # Online agent still exists
        resp = await client.get(f"/api/v1/projects/{project_id}/worktrees")
        worktrees = resp.json()
        assert len(worktrees) == 1
        assert worktrees[0]["id"] == wt_online_id
        assert worktrees[0]["status"] == "online"

    async def test_returns_zero_when_no_offline(self, client: AsyncClient) -> None:
        """Returns zero count when there are no offline agents."""
        project = await _create_project_via_api(client)
        api_key = project["api_key"]
        project_id = project["id"]

        # Register one online agent
        await _register_and_get_token(client, api_key, "/repo/wt-alive")

        resp = await client.post(f"/api/v1/projects/{project_id}/worktrees/remove-offline")
        assert resp.status_code == 200
        assert resp.json() == {"removed_count": 0}
