"""Unit tests for the Agent bounded context."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.repository import AgentRepository
from src.agent.services import AgentService
from src.board.models import Epic, Feature, Project, Task
from src.board.repository import BoardRepository

# --- Helpers ---


async def _create_project(db: AsyncSession) -> Project:
    project = Project(name=f"test-{uuid.uuid4().hex[:8]}", description="Test project")
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


async def _create_task_chain(db: AsyncSession, project: Project) -> Task:
    """Create a project → epic → feature → task chain and return the task."""
    epic = Epic(project_id=project.id, title="Test Epic", position=0)
    db.add(epic)
    await db.commit()
    await db.refresh(epic)

    feature = Feature(epic_id=epic.id, title="Test Feature", position=0)
    db.add(feature)
    await db.commit()
    await db.refresh(feature)

    task = Task(
        feature_id=feature.id,
        title="Test Task",
        description="Do something",
        priority="normal",
        position=0,
        status="assigned",
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


# --- Repository Tests ---


class TestAgentRepository:
    async def test_upsert_worktree_creates_new(self, db_session: AsyncSession) -> None:
        project = await _create_project(db_session)
        repo = AgentRepository(db_session)

        worktree, is_new = await repo.upsert_worktree(project.id, "/repo/wt-auth", "wt-auth")

        assert is_new is True
        assert worktree.worktree_path == "/repo/wt-auth"
        assert worktree.branch_name == "wt-auth"
        assert worktree.status == "online"
        assert worktree.project_id == project.id

    async def test_upsert_worktree_reconnects_existing(self, db_session: AsyncSession) -> None:
        project = await _create_project(db_session)
        repo = AgentRepository(db_session)

        wt1, is_new1 = await repo.upsert_worktree(project.id, "/repo/wt-auth", "wt-auth")
        assert is_new1 is True

        # Set it offline first
        await repo.set_worktree_offline(wt1.id)

        wt2, is_new2 = await repo.upsert_worktree(project.id, "/repo/wt-auth", "wt-auth-v2")
        assert is_new2 is False
        assert wt2.id == wt1.id
        assert wt2.status == "online"
        assert wt2.branch_name == "wt-auth-v2"

    async def test_create_and_get_session(self, db_session: AsyncSession) -> None:
        project = await _create_project(db_session)
        repo = AgentRepository(db_session)

        worktree, _ = await repo.upsert_worktree(project.id, "/repo/wt-api", "wt-api")
        session = await repo.create_session(worktree.id)

        assert session.worktree_id == worktree.id
        assert session.status == "active"

        active = await repo.get_active_session(worktree.id)
        assert active is not None
        assert active.id == session.id

    async def test_update_heartbeat(self, db_session: AsyncSession) -> None:
        project = await _create_project(db_session)
        repo = AgentRepository(db_session)

        worktree, _ = await repo.upsert_worktree(project.id, "/repo/wt-api", "wt-api")
        session = await repo.create_session(worktree.id)
        original_hb = session.last_heartbeat

        updated = await repo.update_heartbeat(session.id)
        assert updated is not None
        assert updated.last_heartbeat >= original_hb

    async def test_end_session(self, db_session: AsyncSession) -> None:
        project = await _create_project(db_session)
        repo = AgentRepository(db_session)

        worktree, _ = await repo.upsert_worktree(project.id, "/repo/wt-api", "wt-api")
        session = await repo.create_session(worktree.id)
        await repo.end_session(session.id)

        active = await repo.get_active_session(worktree.id)
        assert active is None

    async def test_get_timed_out_sessions(self, db_session: AsyncSession) -> None:
        project = await _create_project(db_session)
        repo = AgentRepository(db_session)

        worktree, _ = await repo.upsert_worktree(project.id, "/repo/wt-api", "wt-api")
        session = await repo.create_session(worktree.id)

        # Manually set heartbeat to the past
        session.last_heartbeat = datetime.now(UTC) - timedelta(minutes=10)
        await db_session.commit()

        cutoff = datetime.now(UTC) - timedelta(minutes=5)
        timed_out = await repo.get_timed_out_sessions(cutoff)
        assert len(timed_out) == 1
        assert timed_out[0].id == session.id

    async def test_get_worktrees_for_project(self, db_session: AsyncSession) -> None:
        project = await _create_project(db_session)
        repo = AgentRepository(db_session)

        await repo.upsert_worktree(project.id, "/repo/wt-a", "wt-a")
        await repo.upsert_worktree(project.id, "/repo/wt-b", "wt-b")

        worktrees = await repo.get_worktrees_for_project(project.id)
        assert len(worktrees) == 2
        paths = {w.worktree_path for w in worktrees}
        assert paths == {"/repo/wt-a", "/repo/wt-b"}

    async def test_get_worktree_by_path(self, db_session: AsyncSession) -> None:
        project = await _create_project(db_session)
        repo = AgentRepository(db_session)
        wt, _ = await repo.upsert_worktree(project.id, "/tmp/test-wt", "wt-test")
        found = await repo.get_worktree_by_path(project.id, "/tmp/test-wt")
        assert found is not None
        assert found.id == wt.id

    async def test_get_worktree_by_path_not_found(self, db_session: AsyncSession) -> None:
        project = await _create_project(db_session)
        repo = AgentRepository(db_session)
        found = await repo.get_worktree_by_path(project.id, "/tmp/nonexistent")
        assert found is None

    async def test_delete_worktree(self, db_session: AsyncSession) -> None:
        project = await _create_project(db_session)
        repo = AgentRepository(db_session)
        wt, _ = await repo.upsert_worktree(project.id, "/tmp/test-del", "wt-del")
        _ = await repo.create_session(wt.id)
        await repo.delete_worktree(wt.id)
        assert await repo.get_worktree(wt.id) is None


# --- Service Tests ---


class TestAgentService:
    async def test_register_new_worktree(self, db_session: AsyncSession) -> None:
        project = await _create_project(db_session)
        service = AgentService(AgentRepository(db_session), BoardRepository(db_session))

        result = await service.register(project.id, "/repo/wt-auth", "wt-auth")

        assert result["resumed"] is False
        assert result["worktree_id"] is not None
        assert result["session_id"] is not None
        assert result["current_task"] is None

    async def test_register_reconnects(self, db_session: AsyncSession) -> None:
        """After unregister (which deletes the record), re-registering creates a fresh worktree."""
        project = await _create_project(db_session)
        service = AgentService(AgentRepository(db_session), BoardRepository(db_session))

        r1 = await service.register(project.id, "/repo/wt-auth", "wt-auth")
        await service.unregister(r1["worktree_id"])  # type: ignore[arg-type]

        # Worktree record is deleted — re-registering creates a new one
        r2 = await service.register(project.id, "/repo/wt-auth", "wt-auth")
        assert r2["resumed"] is False
        assert r2["worktree_id"] is not None
        assert r2["session_id"] is not None

    async def test_register_resumes_with_current_task(self, db_session: AsyncSession) -> None:
        project = await _create_project(db_session)
        task = await _create_task_chain(db_session, project)
        service = AgentService(AgentRepository(db_session), BoardRepository(db_session))

        r1 = await service.register(project.id, "/repo/wt-auth", "wt-auth")
        await service.start_task(r1["worktree_id"], task.id)  # type: ignore[arg-type]

        # Simulate reconnection (register again)
        r2 = await service.register(project.id, "/repo/wt-auth", "wt-auth")
        assert r2["current_task"] is not None
        assert r2["current_task"]["id"] == task.id  # type: ignore[index]

    async def test_heartbeat(self, db_session: AsyncSession) -> None:
        project = await _create_project(db_session)
        service = AgentService(AgentRepository(db_session), BoardRepository(db_session))

        reg = await service.register(project.id, "/repo/wt-auth", "wt-auth")
        result = await service.heartbeat(reg["worktree_id"])  # type: ignore[arg-type]
        assert result["status"] == "ok"
        assert result["last_heartbeat"] is not None

    async def test_heartbeat_no_session_raises(self, db_session: AsyncSession) -> None:
        service = AgentService(AgentRepository(db_session), BoardRepository(db_session))
        with pytest.raises(ValueError, match="No active session"):
            await service.heartbeat(uuid.uuid4())

    async def test_start_task(self, db_session: AsyncSession) -> None:
        project = await _create_project(db_session)
        task = await _create_task_chain(db_session, project)
        service = AgentService(AgentRepository(db_session), BoardRepository(db_session))

        reg = await service.register(project.id, "/repo/wt-auth", "wt-auth")
        result = await service.start_task(reg["worktree_id"], task.id)  # type: ignore[arg-type]
        assert result["task_id"] == task.id
        assert result["status"] == "in_progress"

        # Verify task status updated in DB
        updated_task = await BoardRepository(db_session).get_task(task.id)
        assert updated_task is not None
        assert updated_task.status == "in_progress"
        assert updated_task.worktree_id == reg["worktree_id"]

    async def test_complete_task(self, db_session: AsyncSession) -> None:
        project = await _create_project(db_session)
        task = await _create_task_chain(db_session, project)
        service = AgentService(AgentRepository(db_session), BoardRepository(db_session))

        reg = await service.register(project.id, "/repo/wt-auth", "wt-auth")
        wt_id = reg["worktree_id"]
        await service.start_task(wt_id, task.id)  # type: ignore[arg-type]
        result = await service.complete_task(wt_id, task.id)  # type: ignore[arg-type]

        assert result["completed_task_id"] == task.id
        assert result["next_task"] is None  # No more tasks

        updated_task = await BoardRepository(db_session).get_task(task.id)
        assert updated_task is not None
        assert updated_task.status == "done"

    async def test_complete_task_returns_next(self, db_session: AsyncSession) -> None:
        project = await _create_project(db_session)
        task1 = await _create_task_chain(db_session, project)

        # Create a second task assigned to the same worktree
        stmt = select(Epic).where(Epic.project_id == project.id)
        epic = (await db_session.execute(stmt)).scalar_one()
        stmt2 = select(Feature).where(Feature.epic_id == epic.id)
        feature = (await db_session.execute(stmt2)).scalar_one()
        task2 = Task(
            feature_id=feature.id,
            title="Second Task",
            description="Next thing",
            priority="normal",
            position=1,
            status="backlog",
        )
        db_session.add(task2)
        await db_session.commit()
        await db_session.refresh(task2)

        service = AgentService(AgentRepository(db_session), BoardRepository(db_session))
        reg = await service.register(project.id, "/repo/wt-auth", "wt-auth")
        wt_id = reg["worktree_id"]

        # Assign task2 to this worktree
        await BoardRepository(db_session).update_task(task2.id, worktree_id=wt_id)

        # Start and complete task1
        await service.start_task(wt_id, task1.id)  # type: ignore[arg-type]
        result = await service.complete_task(wt_id, task1.id)  # type: ignore[arg-type]

        assert result["next_task"] is not None
        assert result["next_task"]["id"] == task2.id  # type: ignore[index]

    async def test_update_task_status(self, db_session: AsyncSession) -> None:
        project = await _create_project(db_session)
        task = await _create_task_chain(db_session, project)
        service = AgentService(AgentRepository(db_session), BoardRepository(db_session))

        reg = await service.register(project.id, "/repo/wt-auth", "wt-auth")
        wt_id = reg["worktree_id"]
        await service.start_task(wt_id, task.id)  # type: ignore[arg-type]
        await service.update_task_status(wt_id, task.id, "review")  # type: ignore[arg-type]

        updated_task = await BoardRepository(db_session).get_task(task.id)
        assert updated_task is not None
        assert updated_task.status == "review"

    async def test_unregister(self, db_session: AsyncSession) -> None:
        """Unregister deletes the worktree record entirely."""
        project = await _create_project(db_session)
        service = AgentService(AgentRepository(db_session), BoardRepository(db_session))

        reg = await service.register(project.id, "/repo/wt-auth", "wt-auth")
        wt_id = reg["worktree_id"]
        await service.unregister(wt_id)  # type: ignore[arg-type]

        # Worktree is deleted, not just set to offline
        worktree = await AgentRepository(db_session).get_worktree(wt_id)  # type: ignore[arg-type]
        assert worktree is None

    async def test_heartbeat_timeout_detection(self, db_session: AsyncSession) -> None:
        project = await _create_project(db_session)
        repo = AgentRepository(db_session)
        service = AgentService(repo, BoardRepository(db_session))

        reg = await service.register(project.id, "/repo/wt-auth", "wt-auth")
        wt_id = reg["worktree_id"]

        # Manually expire the session heartbeat
        session = await repo.get_active_session(wt_id)  # type: ignore[arg-type]
        assert session is not None
        session.last_heartbeat = datetime.now(UTC) - timedelta(minutes=10)
        await db_session.commit()

        affected = await service.check_heartbeat_timeouts()
        assert wt_id in affected

        worktree = await repo.get_worktree(wt_id)  # type: ignore[arg-type]
        assert worktree is not None
        assert worktree.status == "offline"

    async def test_get_worktrees_for_project(self, db_session: AsyncSession) -> None:
        project = await _create_project(db_session)
        service = AgentService(AgentRepository(db_session), BoardRepository(db_session))

        await service.register(project.id, "/repo/wt-a", "wt-a")
        await service.register(project.id, "/repo/wt-b", "wt-b")

        worktrees = await service.get_worktrees_for_project(project.id)
        assert len(worktrees) == 2
        paths = {w["worktree_path"] for w in worktrees}
        assert paths == {"/repo/wt-a", "/repo/wt-b"}
