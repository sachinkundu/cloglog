"""Integration tests for task-level dependencies (F-11 PR B)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.board.models import Epic, Feature, Task
from src.board.repository import BoardRepository
from src.board.services import BoardService


async def _make_tree(db: AsyncSession, project_id: uuid.UUID, n_tasks: int = 3) -> list[Task]:
    """Create one epic/feature and ``n_tasks`` tasks, return the tasks in
    insertion order."""
    epic = Epic(project_id=project_id, title="E", position=0)
    db.add(epic)
    await db.commit()
    await db.refresh(epic)
    feature = Feature(epic_id=epic.id, title="F", position=0)
    db.add(feature)
    await db.commit()
    await db.refresh(feature)
    tasks = []
    for i in range(n_tasks):
        t = Task(
            feature_id=feature.id,
            title=f"t{i}",
            description="",
            priority="normal",
            position=i,
            status="backlog",
            task_type="task",
            number=i + 1,
        )
        db.add(t)
        await db.commit()
        await db.refresh(t)
        tasks.append(t)
    return tasks


async def _make_project(db: AsyncSession) -> uuid.UUID:
    from src.board.models import Project

    p = Project(name=f"tp-{uuid.uuid4().hex[:8]}", description="")
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p.id


class TestServiceLayer:
    async def test_add_and_exists(self, db_session: AsyncSession) -> None:
        pid = await _make_project(db_session)
        t1, t2, _ = await _make_tree(db_session, pid)
        svc = BoardService(BoardRepository(db_session))

        await svc.add_task_dependency(t1.id, t2.id)
        assert await svc._repo.get_task_dependency_exists(t1.id, t2.id) is True

    async def test_self_loop_rejected(self, db_session: AsyncSession) -> None:
        pid = await _make_project(db_session)
        t1, _, _ = await _make_tree(db_session, pid)
        svc = BoardService(BoardRepository(db_session))

        with pytest.raises(ValueError, match="cannot depend on itself"):
            await svc.add_task_dependency(t1.id, t1.id)

    async def test_duplicate_rejected(self, db_session: AsyncSession) -> None:
        pid = await _make_project(db_session)
        t1, t2, _ = await _make_tree(db_session, pid)
        svc = BoardService(BoardRepository(db_session))

        await svc.add_task_dependency(t1.id, t2.id)
        with pytest.raises(ValueError, match="DUPLICATE"):
            await svc.add_task_dependency(t1.id, t2.id)

    async def test_cycle_rejected(self, db_session: AsyncSession) -> None:
        """t1→t2, then t2→t1 should reject."""
        pid = await _make_project(db_session)
        t1, t2, _ = await _make_tree(db_session, pid)
        svc = BoardService(BoardRepository(db_session))

        await svc.add_task_dependency(t1.id, t2.id)
        with pytest.raises(ValueError, match="create a cycle"):
            await svc.add_task_dependency(t2.id, t1.id)

    async def test_transitive_cycle_rejected(self, db_session: AsyncSession) -> None:
        """t1→t2, t2→t3, then t3→t1 should reject as transitive cycle."""
        pid = await _make_project(db_session)
        t1, t2, t3 = await _make_tree(db_session, pid)
        svc = BoardService(BoardRepository(db_session))

        await svc.add_task_dependency(t1.id, t2.id)
        await svc.add_task_dependency(t2.id, t3.id)
        with pytest.raises(ValueError, match="create a cycle"):
            await svc.add_task_dependency(t3.id, t1.id)

    async def test_cross_project_rejected(self, db_session: AsyncSession) -> None:
        pid_a = await _make_project(db_session)
        pid_b = await _make_project(db_session)
        (t_a,) = await _make_tree(db_session, pid_a, 1)
        (t_b,) = await _make_tree(db_session, pid_b, 1)
        svc = BoardService(BoardRepository(db_session))

        with pytest.raises(ValueError, match="same project"):
            await svc.add_task_dependency(t_a.id, t_b.id)

    async def test_task_not_found(self, db_session: AsyncSession) -> None:
        pid = await _make_project(db_session)
        (t1,) = await _make_tree(db_session, pid, 1)
        svc = BoardService(BoardRepository(db_session))

        with pytest.raises(ValueError, match="not found"):
            await svc.add_task_dependency(t1.id, uuid.uuid4())

    async def test_remove(self, db_session: AsyncSession) -> None:
        pid = await _make_project(db_session)
        t1, t2, _ = await _make_tree(db_session, pid)
        svc = BoardService(BoardRepository(db_session))

        await svc.add_task_dependency(t1.id, t2.id)
        assert await svc.remove_task_dependency(t1.id, t2.id) is True
        assert await svc.remove_task_dependency(t1.id, t2.id) is False


class TestRoutes:
    async def test_add_and_remove(self, client: AsyncClient) -> None:
        # Setup: project, epic, feature, two tasks
        project = (
            await client.post(
                "/api/v1/projects",
                json={"name": f"td-{uuid.uuid4().hex[:8]}", "description": ""},
            )
        ).json()
        pid = project["id"]
        epic = (await client.post(f"/api/v1/projects/{pid}/epics", json={"title": "E"})).json()
        eid = epic["id"]
        feature = (
            await client.post(f"/api/v1/projects/{pid}/epics/{eid}/features", json={"title": "F"})
        ).json()
        fid = feature["id"]
        t1 = (
            await client.post(
                f"/api/v1/projects/{pid}/features/{fid}/tasks",
                json={
                    "title": "t1",
                    "description": "",
                    "priority": "normal",
                    "position": 0,
                },
            )
        ).json()
        t2 = (
            await client.post(
                f"/api/v1/projects/{pid}/features/{fid}/tasks",
                json={
                    "title": "t2",
                    "description": "",
                    "priority": "normal",
                    "position": 1,
                },
            )
        ).json()

        resp = await client.post(
            f"/api/v1/tasks/{t1['id']}/dependencies",
            json={"depends_on_id": t2["id"]},
        )
        assert resp.status_code == 201

        resp = await client.post(
            f"/api/v1/tasks/{t1['id']}/dependencies",
            json={"depends_on_id": t2["id"]},
        )
        assert resp.status_code == 409

        # Self-loop
        resp = await client.post(
            f"/api/v1/tasks/{t1['id']}/dependencies",
            json={"depends_on_id": t1["id"]},
        )
        assert resp.status_code == 400

        resp = await client.delete(
            f"/api/v1/tasks/{t1['id']}/dependencies/{t2['id']}",
        )
        assert resp.status_code == 204

        # Double-delete → 404
        resp = await client.delete(
            f"/api/v1/tasks/{t1['id']}/dependencies/{t2['id']}",
        )
        assert resp.status_code == 404

    async def test_route_rejects_garbage_mcp_bearer(self, client: AsyncClient) -> None:
        """Regression: CurrentMcpOrDashboard must reject Bearer garbage +
        X-MCP-Request on the new task-dep route (same bar as feature-dep).
        No setup needed — the hybrid dep rejects before the handler runs."""
        resp = await client.post(
            f"/api/v1/tasks/{uuid.uuid4()}/dependencies",
            json={"depends_on_id": str(uuid.uuid4())},
            headers={
                "Authorization": "Bearer garbage",
                "X-MCP-Request": "true",
                "X-Dashboard-Key": "",
            },
        )
        assert resp.status_code == 401


class TestBlockerQueryTaskExtension:
    """B4 — get_unresolved_blockers should now emit task blockers too."""

    async def test_task_blocker_emitted_when_upstream_unresolved(
        self, db_session: AsyncSession
    ) -> None:
        pid = await _make_project(db_session)
        t_up, t_down, _ = await _make_tree(db_session, pid)
        svc = BoardService(BoardRepository(db_session))

        await svc.add_task_dependency(t_down.id, t_up.id)

        blockers = await svc.get_unresolved_blockers(t_down.id)
        assert len(blockers) == 1
        b = blockers[0]
        assert b["kind"] == "task"
        assert b["task_id"] == str(t_up.id)
        assert b["task_number"] == t_up.number
        assert b["status"] == "backlog"

    async def test_task_blocker_resolves_on_review_with_pr_url(
        self, db_session: AsyncSession
    ) -> None:
        pid = await _make_project(db_session)
        t_up, t_down, _ = await _make_tree(db_session, pid)
        t_up.status = "review"
        t_up.pr_url = "https://github.com/x/y/pull/1"
        await db_session.commit()
        svc = BoardService(BoardRepository(db_session))

        await svc.add_task_dependency(t_down.id, t_up.id)
        assert await svc.get_unresolved_blockers(t_down.id) == []

    async def test_feature_and_task_blockers_ordered(self, db_session: AsyncSession) -> None:
        """Feature blockers first, then task blockers — stable order."""
        from src.board.models import FeatureDependency

        pid = await _make_project(db_session)
        # F-up has an incomplete task. F-down contains t_down + t_block (blocker).
        epic = Epic(project_id=pid, title="E", position=0)
        db_session.add(epic)
        await db_session.commit()
        await db_session.refresh(epic)
        f_up = Feature(epic_id=epic.id, title="F-up", position=0, number=1)
        f_down = Feature(epic_id=epic.id, title="F-down", position=1, number=2)
        db_session.add_all([f_up, f_down])
        await db_session.commit()
        await db_session.refresh(f_up)
        await db_session.refresh(f_down)

        t_up_task = Task(
            feature_id=f_up.id,
            title="upstream",
            description="",
            priority="normal",
            position=0,
            status="backlog",
            task_type="task",
            number=10,
        )
        t_block = Task(
            feature_id=f_down.id,
            title="block",
            description="",
            priority="normal",
            position=0,
            status="backlog",
            task_type="task",
            number=20,
        )
        t_down = Task(
            feature_id=f_down.id,
            title="down",
            description="",
            priority="normal",
            position=1,
            status="backlog",
            task_type="task",
            number=30,
        )
        db_session.add_all([t_up_task, t_block, t_down])
        await db_session.commit()
        await db_session.refresh(t_block)
        await db_session.refresh(t_down)

        db_session.add(FeatureDependency(feature_id=f_down.id, depends_on_id=f_up.id))
        await db_session.commit()
        svc = BoardService(BoardRepository(db_session))
        await svc.add_task_dependency(t_down.id, t_block.id)

        blockers = await svc.get_unresolved_blockers(t_down.id)
        kinds = [b["kind"] for b in blockers]
        # Feature blocker first, task blocker second
        assert kinds == ["feature", "task"]
