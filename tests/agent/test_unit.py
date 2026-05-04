"""Unit tests for the Agent bounded context."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.exceptions import TaskBlockedError
from src.agent.repository import AgentRepository
from src.agent.scheduler import run_heartbeat_checker
from src.agent.services import AgentService
from src.board.models import Epic, Feature, Project, Task
from src.board.repository import BoardRepository
from src.document.repository import DocumentRepository

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


# --- T-278 per-PR review root resolver DB primitives ---


class TestFindWorktreeByBranchAnyStatus:
    """T-278: the per-PR review-root resolver needs a lookup that does NOT
    filter by ``status='online'`` — a recently-offline worktree still points
    at a valid checkout on disk, which beats prod main.
    """

    async def test_returns_online_row(self, db_session: AsyncSession) -> None:
        project = await _create_project(db_session)
        repo = AgentRepository(db_session)

        created, _ = await repo.upsert_worktree(project.id, "/repo/wt-t278", "wt-t278")
        found = await repo.find_worktree_by_branch_any_status(project.id, "wt-t278")

        assert found is not None
        assert found.id == created.id
        assert found.status == "online"

    async def test_returns_offline_row(self, db_session: AsyncSession) -> None:
        """``get_worktree_by_branch`` would return None here; the any-status
        variant must NOT — T-278's resolver prefers a stale worktree path
        over prod main.
        """
        project = await _create_project(db_session)
        repo = AgentRepository(db_session)

        created, _ = await repo.upsert_worktree(project.id, "/repo/wt-t278", "wt-t278")
        await repo.set_worktree_offline(created.id)

        via_online = await repo.get_worktree_by_branch(project.id, "wt-t278")
        assert via_online is None, (
            "Online-gated lookup must reject offline rows — that is its contract."
        )

        via_any = await repo.find_worktree_by_branch_any_status(project.id, "wt-t278")
        assert via_any is not None
        assert via_any.id == created.id
        assert via_any.status == "offline"

    async def test_empty_branch_returns_none(self, db_session: AsyncSession) -> None:
        """Empty branch is the historical data-trap; must short-circuit to
        None regardless of row count (same rule as the online-gated lookup).
        """
        project = await _create_project(db_session)
        repo = AgentRepository(db_session)

        assert await repo.find_worktree_by_branch_any_status(project.id, "") is None

    async def test_no_match_returns_none(self, db_session: AsyncSession) -> None:
        project = await _create_project(db_session)
        repo = AgentRepository(db_session)

        await repo.upsert_worktree(project.id, "/repo/wt-a", "wt-a")
        assert (
            await repo.find_worktree_by_branch_any_status(project.id, "wt-does-not-exist") is None
        )


class TestMakeWorktreeQueryFactory:
    """T-278 OHS boundary: ``make_worktree_query`` returns an object that
    implements ``IWorktreeQuery`` and delegates to ``AgentRepository``
    without leaking the ORM row across the seam.
    """

    async def test_factory_returns_protocol_implementation(self, db_session: AsyncSession) -> None:
        from src.agent.interfaces import IWorktreeQuery, WorktreeRow
        from src.agent.services import make_worktree_query

        project = await _create_project(db_session)
        repo = AgentRepository(db_session)
        created, _ = await repo.upsert_worktree(project.id, "/repo/wt-t278", "wt-t278")

        query = make_worktree_query(db_session)
        # Runtime-check the Protocol surface. We do not use ``isinstance``
        # against a non-runtime-checkable Protocol; instead we assert the
        # behaviour the Protocol requires.
        assert hasattr(query, "find_by_branch")
        _ = IWorktreeQuery  # import used only for the type annotation above

        row = await query.find_by_branch(project.id, "wt-t278")
        assert row is not None
        assert isinstance(row, WorktreeRow), (
            f"Factory must return a WorktreeRow DTO, got {type(row).__name__}"
        )
        assert row.id == created.id
        assert row.worktree_path == "/repo/wt-t278"
        assert row.branch_name == "wt-t278"

    async def test_factory_returns_none_for_missing(self, db_session: AsyncSession) -> None:
        from src.agent.services import make_worktree_query

        project = await _create_project(db_session)
        query = make_worktree_query(db_session)
        assert await query.find_by_branch(project.id, "wt-missing") is None


class TestFindWorktreeByPrUrl:
    """T-281 Path 0: resolver follows the canonical ``tasks.pr_url →
    task.worktree_id → worktrees.id`` chain — the same join webhook routing
    uses in ``_resolve_agent`` (``src/gateway/webhook_consumers.py``).

    Exists because ``find_by_branch`` misses on main-agent close-out PRs:
    the main agent never registers a worktree row for the close-out branch
    (spawning one would cause infinite recursion — each close-out would
    itself need a close-out). The task-binding chain does the right thing
    for both close-out PRs (returns the main agent's worktree) AND regular
    agent PRs (returns the same physical path as branch lookup would).
    """

    async def test_empty_pr_url_short_circuits_to_none(self, db_session: AsyncSession) -> None:
        """Empty pr_url must short-circuit without a DB round-trip — mirror
        of the empty-branch guard on ``find_by_branch``.
        """
        from src.agent.services import make_worktree_query

        project = await _create_project(db_session)
        query = make_worktree_query(db_session)
        assert await query.find_by_pr_url(project.id, "") is None

    async def test_hit_returns_task_bound_worktree_row(self, db_session: AsyncSession) -> None:
        """Task with ``pr_url`` set and ``worktree_id`` pointing at a
        worktree → resolver returns that worktree's row via the join.
        """
        from src.agent.interfaces import WorktreeRow
        from src.agent.services import make_worktree_query

        project = await _create_project(db_session)
        repo = AgentRepository(db_session)
        created, _ = await repo.upsert_worktree(project.id, "/repo/wt-t281", "wt-t281")

        task = await _create_task_chain(db_session, project)
        task.pr_url = "https://github.com/foo/bar/pull/281"
        task.status = "review"
        task.worktree_id = created.id
        await db_session.commit()

        query = make_worktree_query(db_session)
        row = await query.find_by_pr_url(project.id, "https://github.com/foo/bar/pull/281")

        assert row is not None
        assert isinstance(row, WorktreeRow), (
            f"Factory must return a WorktreeRow DTO, got {type(row).__name__}"
        )
        assert row.id == created.id
        assert row.worktree_path == "/repo/wt-t281"
        assert row.branch_name == "wt-t281"

    async def test_unknown_pr_url_returns_none(self, db_session: AsyncSession) -> None:
        """No task matches → None."""
        from src.agent.services import make_worktree_query

        project = await _create_project(db_session)
        query = make_worktree_query(db_session)
        assert (
            await query.find_by_pr_url(project.id, "https://github.com/foo/bar/pull/9999") is None
        )

    async def test_task_without_worktree_id_returns_none(self, db_session: AsyncSession) -> None:
        """Task exists with pr_url but has no ``worktree_id`` binding yet —
        chain cannot complete, so the resolver must fall through.
        """
        from src.agent.services import make_worktree_query

        project = await _create_project(db_session)
        task = await _create_task_chain(db_session, project)
        task.pr_url = "https://github.com/foo/bar/pull/281"
        task.status = "review"
        # Leave task.worktree_id = None
        await db_session.commit()

        query = make_worktree_query(db_session)
        assert await query.find_by_pr_url(project.id, "https://github.com/foo/bar/pull/281") is None

    async def test_cross_project_returns_none(self, db_session: AsyncSession) -> None:
        """Project-scoped join — a pr_url bound to project A is invisible
        when the resolver asks about project B. Mirrors the scoping in
        ``find_task_by_pr_url_for_project`` (``src/board/repository.py``).
        """
        from src.agent.services import make_worktree_query

        project_a = await _create_project(db_session)
        project_b = await _create_project(db_session)
        repo = AgentRepository(db_session)
        created, _ = await repo.upsert_worktree(project_a.id, "/repo/wt-a", "wt-a")

        task = await _create_task_chain(db_session, project_a)
        task.pr_url = "https://github.com/foo/bar/pull/281"
        task.status = "review"
        task.worktree_id = created.id
        await db_session.commit()

        query = make_worktree_query(db_session)
        assert (
            await query.find_by_pr_url(project_b.id, "https://github.com/foo/bar/pull/281") is None
        )


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

        # T-262 round 3 (Codex): the route declares response_model=RegisterResponse,
        # whose current_task is TaskInfo. After T-262 added required `number` to
        # TaskInfo, the hand-built dict in AgentService.register() must include
        # every required field or FastAPI's response validation returns 500
        # instead of 201 on every reconnect with an active task. Pin the full
        # round-trip so a future schema change can't silently break this path.
        from src.agent.schemas import RegisterResponse

        validated = RegisterResponse.model_validate(r2)
        assert validated.current_task is not None
        assert validated.current_task.number == task.number
        assert validated.current_task.pr_url == task.pr_url

    async def test_register_stores_branch_name_from_caller(self, db_session: AsyncSession) -> None:
        """The backend is a pure pass-through for ``branch_name``. The caller
        (the MCP server or a direct API client) derives it and sends it; the
        backend stores exactly what it received. This test pins that contract
        so a future refactor can't silently reintroduce a backend-side
        filesystem probe on every registration."""
        project = await _create_project(db_session)
        service = AgentService(AgentRepository(db_session), BoardRepository(db_session))
        result = await service.register(project.id, "/vm-only/path/invisible", "wt-from-mcp")

        worktree = await AgentRepository(db_session).get_worktree(result["worktree_id"])  # type: ignore[arg-type]
        assert worktree is not None
        assert worktree.branch_name == "wt-from-mcp"

    async def test_register_reconnect_preserves_branch_when_caller_sends_empty(
        self, db_session: AsyncSession
    ) -> None:
        """T-254 defensive regression: if a reconnect arrives with empty
        ``branch_name`` (e.g. MCP probe hit a transient git failure), the
        repository must NOT wipe the previously-stored name — that would
        reopen the empty-branch data trap."""
        project = await _create_project(db_session)
        service = AgentService(AgentRepository(db_session), BoardRepository(db_session))

        r1 = await service.register(project.id, "/vm-only/wt-preserve", "wt-preserve")
        worktree = await AgentRepository(db_session).get_worktree(r1["worktree_id"])  # type: ignore[arg-type]
        assert worktree is not None
        assert worktree.branch_name == "wt-preserve"

        # Reconnect with empty branch_name — row already exists.
        r2 = await service.register(project.id, "/vm-only/wt-preserve", "")
        assert r2["worktree_id"] == r1["worktree_id"]
        worktree2 = await AgentRepository(db_session).get_worktree(r2["worktree_id"])  # type: ignore[arg-type]
        assert worktree2 is not None
        assert worktree2.branch_name == "wt-preserve"

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

    async def test_complete_task_blocked(self, db_session: AsyncSession) -> None:
        """complete_task always raises — agents cannot mark tasks done."""
        project = await _create_project(db_session)
        task = await _create_task_chain(db_session, project)
        service = AgentService(AgentRepository(db_session), BoardRepository(db_session))

        reg = await service.register(project.id, "/repo/wt-auth", "wt-auth")
        wt_id = reg["worktree_id"]
        await service.start_task(wt_id, task.id)  # type: ignore[arg-type]

        with pytest.raises(ValueError, match="Agents cannot mark tasks as done"):
            await service.complete_task(wt_id, task.id)  # type: ignore[arg-type]

    async def test_update_task_status(self, db_session: AsyncSession) -> None:
        project = await _create_project(db_session)
        task = await _create_task_chain(db_session, project)
        service = AgentService(AgentRepository(db_session), BoardRepository(db_session))

        reg = await service.register(project.id, "/repo/wt-auth", "wt-auth")
        wt_id = reg["worktree_id"]
        await service.start_task(wt_id, task.id)  # type: ignore[arg-type]
        await service.update_task_status(
            wt_id,
            task.id,
            "review",
            pr_url="https://github.com/test/repo/pull/1",  # type: ignore[arg-type]
        )

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

    async def test_start_task_blocked_when_active_task(self, db_session: AsyncSession) -> None:
        """Cannot start a second task when agent already has one in_progress."""
        project = await _create_project(db_session)
        task1 = await _create_task_chain(db_session, project)
        # Create a second task in the same feature
        task2 = Task(
            feature_id=task1.feature_id,
            title="Second Task",
            description="Another task",
            priority="normal",
            position=1,
            status="assigned",
        )
        db_session.add(task2)
        await db_session.commit()
        await db_session.refresh(task2)

        service = AgentService(AgentRepository(db_session), BoardRepository(db_session))
        reg = await service.register(project.id, "/repo/wt-guard", "wt-guard")
        wt_id = reg["worktree_id"]

        # Assign both tasks to the worktree
        await BoardRepository(db_session).update_task(task1.id, worktree_id=wt_id)
        await BoardRepository(db_session).update_task(task2.id, worktree_id=wt_id)

        # Start first task
        await service.start_task(wt_id, task1.id)  # type: ignore[arg-type]

        # Try to start second — should fail
        with pytest.raises(ValueError, match="Cannot start task.*already has active"):
            await service.start_task(wt_id, task2.id)  # type: ignore[arg-type]

    async def test_start_task_allowed_after_previous_done(self, db_session: AsyncSession) -> None:
        """Can start a new task after the previous one is moved to done."""
        project = await _create_project(db_session)
        task1 = await _create_task_chain(db_session, project)
        task2 = Task(
            feature_id=task1.feature_id,
            title="Second Task",
            description="Another task",
            priority="normal",
            position=1,
            status="assigned",
        )
        db_session.add(task2)
        await db_session.commit()
        await db_session.refresh(task2)

        service = AgentService(AgentRepository(db_session), BoardRepository(db_session))
        reg = await service.register(project.id, "/repo/wt-guard2", "wt-guard2")
        wt_id = reg["worktree_id"]

        await BoardRepository(db_session).update_task(task1.id, worktree_id=wt_id)
        await BoardRepository(db_session).update_task(task2.id, worktree_id=wt_id)

        # Start and complete first task (simulate user marking done)
        await service.start_task(wt_id, task1.id)  # type: ignore[arg-type]
        await BoardRepository(db_session).update_task(task1.id, status="done")

        # Starting second task should now work
        result = await service.start_task(wt_id, task2.id)  # type: ignore[arg-type]
        assert result["status"] == "in_progress"

    async def test_review_requires_pr_url(self, db_session: AsyncSession) -> None:
        """Moving any task to review requires a pr_url."""
        project = await _create_project(db_session)
        task = await _create_task_chain(db_session, project)
        service = AgentService(AgentRepository(db_session), BoardRepository(db_session))

        reg = await service.register(project.id, "/repo/wt-pr", "wt-pr")
        wt_id = reg["worktree_id"]
        await service.start_task(wt_id, task.id)  # type: ignore[arg-type]

        # Try moving to review without pr_url — should fail
        with pytest.raises(ValueError, match="Cannot move task to review without a PR URL"):
            await service.update_task_status(wt_id, task.id, "review")  # type: ignore[arg-type]

    async def test_review_to_in_progress_allowed(self, db_session: AsyncSession) -> None:
        """Agent can move task from review back to in_progress (e.g. addressing PR comments)."""
        project = await _create_project(db_session)
        task = await _create_task_chain(db_session, project)
        service = AgentService(AgentRepository(db_session), BoardRepository(db_session))

        reg = await service.register(project.id, "/repo/wt-rev", "wt-rev")
        wt_id = reg["worktree_id"]
        await service.start_task(wt_id, task.id)  # type: ignore[arg-type]

        # Move to review with PR URL
        await service.update_task_status(
            wt_id,
            task.id,
            "review",
            pr_url="https://github.com/test/repo/pull/1",  # type: ignore[arg-type]
        )
        updated = await BoardRepository(db_session).get_task(task.id)
        assert updated is not None
        assert updated.status == "review"

        # Move back to in_progress
        await service.update_task_status(wt_id, task.id, "in_progress")  # type: ignore[arg-type]
        updated = await BoardRepository(db_session).get_task(task.id)
        assert updated is not None
        assert updated.status == "in_progress"

    async def test_agent_cannot_move_to_done(self, db_session: AsyncSession) -> None:
        """Agent cannot move regular task to done via update_task_status."""
        project = await _create_project(db_session)
        task = await _create_task_chain(db_session, project)
        service = AgentService(AgentRepository(db_session), BoardRepository(db_session))

        reg = await service.register(project.id, "/repo/wt-done", "wt-done")
        wt_id = reg["worktree_id"]
        await service.start_task(wt_id, task.id)  # type: ignore[arg-type]

        with pytest.raises(ValueError, match="Agents cannot mark tasks as done"):
            await service.update_task_status(wt_id, task.id, "done")  # type: ignore[arg-type]

    async def test_close_off_task_can_be_marked_done_by_agent(
        self, db_session: AsyncSession
    ) -> None:
        """T-395: close-off tasks (close_off_worktree_id non-null) may be marked done
        by the close-wave supervisor without user intervention.

        Pin for the carve-out in src/agent/services.py::update_task_status:
        is_close_off_task = task.close_off_worktree_id is not None.
        """
        project = await _create_project(db_session)
        task = await _create_task_chain(db_session, project)
        service = AgentService(AgentRepository(db_session), BoardRepository(db_session))
        board_repo = BoardRepository(db_session)

        # Register the main agent (supervisor calling close-wave)
        reg = await service.register(project.id, "/repo/wt-main", "wt-main")
        main_wt_id = reg["worktree_id"]

        # Register a target worktree (the one being closed)
        target_reg = await service.register(project.id, "/repo/wt-target", "wt-target")
        target_wt_id = target_reg["worktree_id"]

        # Mark the task as a close-off task by setting close_off_worktree_id
        await board_repo.update_task(task.id, close_off_worktree_id=target_wt_id)  # type: ignore[arg-type]
        await board_repo.update_task(task.id, worktree_id=main_wt_id)  # type: ignore[arg-type]

        # Start the close-off task (backlog → in_progress)
        await service.start_task(main_wt_id, task.id)  # type: ignore[arg-type]

        # Agent can mark close-off task done directly (T-395 carve-out)
        await service.update_task_status(main_wt_id, task.id, "done")  # type: ignore[arg-type]

        updated = await board_repo.get_task(task.id)
        assert updated is not None
        assert updated.status == "done"

    async def test_regular_task_still_blocked_from_done_by_agent(
        self, db_session: AsyncSession
    ) -> None:
        """T-395: the close-off carve-out must not apply to regular tasks.

        close_off_worktree_id=None means the task is a regular agent task;
        the user-only-done invariant (src/agent/services.py:502-508) must
        still block agent-driven done transitions for those.
        """
        project = await _create_project(db_session)
        task = await _create_task_chain(db_session, project)
        service = AgentService(AgentRepository(db_session), BoardRepository(db_session))

        reg = await service.register(project.id, "/repo/wt-regular", "wt-regular")
        wt_id = reg["worktree_id"]
        await service.start_task(wt_id, task.id)  # type: ignore[arg-type]

        # Regular task — close_off_worktree_id is None — must still be blocked
        assert task.close_off_worktree_id is None
        with pytest.raises(ValueError, match="Agents cannot mark tasks as done"):
            await service.update_task_status(wt_id, task.id, "done")  # type: ignore[arg-type]

    async def test_start_task_blocked_when_task_in_review(self, db_session: AsyncSession) -> None:
        """Cannot start a new task when agent has one in review status."""
        project = await _create_project(db_session)
        task1 = await _create_task_chain(db_session, project)
        task2 = Task(
            feature_id=task1.feature_id,
            title="Second Task",
            description="Another task",
            priority="normal",
            position=1,
            status="assigned",
        )
        db_session.add(task2)
        await db_session.commit()
        await db_session.refresh(task2)

        service = AgentService(AgentRepository(db_session), BoardRepository(db_session))
        reg = await service.register(project.id, "/repo/wt-rev-blk", "wt-rev-blk")
        wt_id = reg["worktree_id"]

        await BoardRepository(db_session).update_task(task1.id, worktree_id=wt_id)
        await BoardRepository(db_session).update_task(task2.id, worktree_id=wt_id)

        # Start task1 and move to review
        await service.start_task(wt_id, task1.id)  # type: ignore[arg-type]
        await service.update_task_status(
            wt_id,
            task1.id,
            "review",
            pr_url="https://github.com/test/repo/pull/1",  # type: ignore[arg-type]
        )

        # Try to start task2 — should fail because task1 is in review
        with pytest.raises(ValueError, match="Cannot start task.*already has active"):
            await service.start_task(wt_id, task2.id)  # type: ignore[arg-type]

    async def test_agent_re_registers_after_timeout(self, db_session: AsyncSession) -> None:
        """An agent that was timed out can re-register and get a new session."""
        project = await _create_project(db_session)
        repo = AgentRepository(db_session)
        service = AgentService(repo, BoardRepository(db_session))

        # Register and start a task
        task = await _create_task_chain(db_session, project)
        reg = await service.register(project.id, "/repo/wt-timeout", "wt-timeout")
        wt_id = reg["worktree_id"]
        await service.start_task(wt_id, task.id)  # type: ignore[arg-type]

        # Simulate timeout
        session = await repo.get_active_session(wt_id)  # type: ignore[arg-type]
        assert session is not None
        session.last_heartbeat = datetime.now(UTC) - timedelta(minutes=10)
        await db_session.commit()
        await service.check_heartbeat_timeouts()

        # Verify timed out
        worktree = await repo.get_worktree(wt_id)  # type: ignore[arg-type]
        assert worktree is not None
        assert worktree.status == "offline"

        # Re-register — should get a new session, resume with current_task
        reg2 = await service.register(project.id, "/repo/wt-timeout", "wt-timeout")
        assert reg2["resumed"] is True
        assert reg2["worktree_id"] == wt_id
        assert reg2["current_task"] is not None
        assert reg2["current_task"]["id"] == task.id  # type: ignore[index]

        # Verify worktree is back online
        worktree = await repo.get_worktree(wt_id)  # type: ignore[arg-type]
        assert worktree is not None
        assert worktree.status == "online"

    # --- report_artifact tests ---

    async def test_report_artifact_sets_path(self, db_session: AsyncSession) -> None:
        """report_artifact stores artifact_path on a spec task in review."""
        project = await _create_project(db_session)
        epic = Epic(project_id=project.id, title="E", position=0)
        db_session.add(epic)
        await db_session.commit()
        await db_session.refresh(epic)

        feature = Feature(epic_id=epic.id, title="F", position=0)
        db_session.add(feature)
        await db_session.commit()
        await db_session.refresh(feature)

        task = Task(
            feature_id=feature.id,
            title="Write spec",
            description="",
            priority="normal",
            position=0,
            status="review",
            task_type="spec",
            pr_url="https://github.com/test/repo/pull/10",
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)

        service = AgentService(AgentRepository(db_session), BoardRepository(db_session))
        reg = await service.register(project.id, "/repo/wt-art", "wt-art")
        wt_id = reg["worktree_id"]

        result = await service.report_artifact(
            wt_id,
            task.id,
            "docs/specs/feature-1.md",  # type: ignore[arg-type]
        )
        assert result["task_id"] == task.id
        assert result["artifact_path"] == "docs/specs/feature-1.md"
        assert result["feature_id"] == feature.id

        updated = await BoardRepository(db_session).get_task(task.id)
        assert updated is not None
        assert updated.artifact_path == "docs/specs/feature-1.md"

    async def test_report_artifact_rejects_non_spec_plan(self, db_session: AsyncSession) -> None:
        """report_artifact rejects impl tasks."""
        project = await _create_project(db_session)
        epic = Epic(project_id=project.id, title="E", position=0)
        db_session.add(epic)
        await db_session.commit()
        await db_session.refresh(epic)

        feature = Feature(epic_id=epic.id, title="F", position=0)
        db_session.add(feature)
        await db_session.commit()
        await db_session.refresh(feature)

        task = Task(
            feature_id=feature.id,
            title="Implement feature",
            description="",
            priority="normal",
            position=0,
            status="review",
            task_type="impl",
            pr_url="https://github.com/test/repo/pull/11",
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)

        service = AgentService(AgentRepository(db_session), BoardRepository(db_session))
        reg = await service.register(project.id, "/repo/wt-art2", "wt-art2")
        wt_id = reg["worktree_id"]

        with pytest.raises(ValueError, match="only spec and plan tasks produce artifacts"):
            await service.report_artifact(
                wt_id,
                task.id,
                "docs/impl.md",  # type: ignore[arg-type]
            )

    async def test_report_artifact_rejects_non_review_status(
        self, db_session: AsyncSession
    ) -> None:
        """report_artifact rejects tasks not in review status."""
        project = await _create_project(db_session)
        epic = Epic(project_id=project.id, title="E", position=0)
        db_session.add(epic)
        await db_session.commit()
        await db_session.refresh(epic)

        feature = Feature(epic_id=epic.id, title="F", position=0)
        db_session.add(feature)
        await db_session.commit()
        await db_session.refresh(feature)

        task = Task(
            feature_id=feature.id,
            title="Write spec",
            description="",
            priority="normal",
            position=0,
            status="in_progress",
            task_type="spec",
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)

        service = AgentService(AgentRepository(db_session), BoardRepository(db_session))
        reg = await service.register(project.id, "/repo/wt-art3", "wt-art3")
        wt_id = reg["worktree_id"]

        with pytest.raises(ValueError, match="must be in 'review' status"):
            await service.report_artifact(
                wt_id,
                task.id,
                "docs/specs/feature.md",  # type: ignore[arg-type]
            )

    async def test_report_artifact_creates_document(self, db_session: AsyncSession) -> None:
        """report_artifact creates a Document record attached to the feature."""
        project = await _create_project(db_session)
        epic = Epic(project_id=project.id, title="E", position=0)
        db_session.add(epic)
        await db_session.commit()
        await db_session.refresh(epic)

        feature = Feature(epic_id=epic.id, title="F", position=0)
        db_session.add(feature)
        await db_session.commit()
        await db_session.refresh(feature)

        task = Task(
            feature_id=feature.id,
            title="Write spec for auth",
            description="",
            priority="normal",
            position=0,
            status="review",
            task_type="spec",
            pr_url="https://github.com/test/repo/pull/12",
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)

        service = AgentService(AgentRepository(db_session), BoardRepository(db_session))
        reg = await service.register(project.id, "/repo/wt-art4", "wt-art4")
        wt_id = reg["worktree_id"]

        await service.report_artifact(
            wt_id,
            task.id,
            "docs/specs/auth.md",  # type: ignore[arg-type]
        )

        doc_repo = DocumentRepository(db_session)
        docs = await doc_repo.get_documents_for_entity("feature", feature.id)
        assert len(docs) == 1
        assert docs[0].doc_type == "spec"
        assert docs[0].source_path == "docs/specs/auth.md"
        assert docs[0].title == "spec — Write spec for auth"
        assert docs[0].attached_to_id == feature.id

    # --- Pipeline guard artifact tests ---

    async def test_pipeline_blocks_plan_when_spec_has_no_artifact(
        self, db_session: AsyncSession
    ) -> None:
        """Plan task blocked when spec is in review with pr_url but no artifact_path."""
        project = await _create_project(db_session)
        epic = Epic(project_id=project.id, title="E", position=0)
        db_session.add(epic)
        await db_session.commit()
        await db_session.refresh(epic)

        feature = Feature(epic_id=epic.id, title="F", position=0)
        db_session.add(feature)
        await db_session.commit()
        await db_session.refresh(feature)

        spec_task = Task(
            feature_id=feature.id,
            title="Write spec",
            description="",
            priority="normal",
            position=0,
            status="review",
            task_type="spec",
            pr_url="https://github.com/test/repo/pull/20",
            number=1,
        )
        plan_task = Task(
            feature_id=feature.id,
            title="Write plan",
            description="",
            priority="normal",
            position=1,
            status="backlog",
            task_type="plan",
            number=2,
        )
        db_session.add_all([spec_task, plan_task])
        await db_session.commit()
        await db_session.refresh(spec_task)
        await db_session.refresh(plan_task)

        service = AgentService(AgentRepository(db_session), BoardRepository(db_session))
        reg = await service.register(project.id, "/repo/wt-pipe1", "wt-pipe1")
        wt_id = reg["worktree_id"]

        with pytest.raises(TaskBlockedError) as excinfo:
            await service.start_task(wt_id, plan_task.id)  # type: ignore[arg-type]
        assert len(excinfo.value.blockers) == 1
        b = excinfo.value.blockers[0]
        assert b["kind"] == "pipeline"
        assert b["reason"] == "artifact_missing"

    async def test_pipeline_allows_plan_when_spec_has_artifact(
        self, db_session: AsyncSession
    ) -> None:
        """Plan task allowed when spec is in review with pr_url AND artifact_path."""
        project = await _create_project(db_session)
        epic = Epic(project_id=project.id, title="E", position=0)
        db_session.add(epic)
        await db_session.commit()
        await db_session.refresh(epic)

        feature = Feature(epic_id=epic.id, title="F", position=0)
        db_session.add(feature)
        await db_session.commit()
        await db_session.refresh(feature)

        spec_task = Task(
            feature_id=feature.id,
            title="Write spec",
            description="",
            priority="normal",
            position=0,
            status="review",
            task_type="spec",
            pr_url="https://github.com/test/repo/pull/21",
            artifact_path="docs/specs/feature.md",
            number=1,
        )
        plan_task = Task(
            feature_id=feature.id,
            title="Write plan",
            description="",
            priority="normal",
            position=1,
            status="backlog",
            task_type="plan",
            number=2,
        )
        db_session.add_all([spec_task, plan_task])
        await db_session.commit()
        await db_session.refresh(spec_task)
        await db_session.refresh(plan_task)

        service = AgentService(AgentRepository(db_session), BoardRepository(db_session))
        reg = await service.register(project.id, "/repo/wt-pipe2", "wt-pipe2")
        wt_id = reg["worktree_id"]

        result = await service.start_task(wt_id, plan_task.id)  # type: ignore[arg-type]
        assert result["status"] == "in_progress"

    async def test_pipeline_allows_done_spec_without_artifact(
        self, db_session: AsyncSession
    ) -> None:
        """Plan task allowed when spec is done (human override), even without artifact_path."""
        project = await _create_project(db_session)
        epic = Epic(project_id=project.id, title="E", position=0)
        db_session.add(epic)
        await db_session.commit()
        await db_session.refresh(epic)

        feature = Feature(epic_id=epic.id, title="F", position=0)
        db_session.add(feature)
        await db_session.commit()
        await db_session.refresh(feature)

        spec_task = Task(
            feature_id=feature.id,
            title="Write spec",
            description="",
            priority="normal",
            position=0,
            status="done",
            task_type="spec",
            number=1,
        )
        plan_task = Task(
            feature_id=feature.id,
            title="Write plan",
            description="",
            priority="normal",
            position=1,
            status="backlog",
            task_type="plan",
            number=2,
        )
        db_session.add_all([spec_task, plan_task])
        await db_session.commit()
        await db_session.refresh(spec_task)
        await db_session.refresh(plan_task)

        service = AgentService(AgentRepository(db_session), BoardRepository(db_session))
        reg = await service.register(project.id, "/repo/wt-pipe3", "wt-pipe3")
        wt_id = reg["worktree_id"]

        result = await service.start_task(wt_id, plan_task.id)  # type: ignore[arg-type]
        assert result["status"] == "in_progress"


# --- Scheduler Tests ---


class TestHeartbeatScheduler:
    async def test_scheduler_calls_check_timeouts(self, db_session: AsyncSession) -> None:
        """The scheduler loop calls check_heartbeat_timeouts on each iteration."""
        call_count = 0

        async def mock_check_timeouts(self: AgentService) -> list:
            nonlocal call_count
            call_count += 1
            return []

        with (
            patch.object(AgentService, "check_heartbeat_timeouts", mock_check_timeouts),
            patch("src.agent.scheduler.async_session_factory") as mock_factory,
        ):
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            # Run the checker with a very short interval, cancel after a brief wait
            task = asyncio.create_task(run_heartbeat_checker(interval_seconds=0))
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        assert call_count >= 1

    async def test_scheduler_survives_exceptions(self, db_session: AsyncSession) -> None:
        """The scheduler continues running even if an iteration raises."""
        call_count = 0

        async def failing_check(self: AgentService) -> list:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("DB connection lost")
            return []

        with (
            patch.object(AgentService, "check_heartbeat_timeouts", failing_check),
            patch("src.agent.scheduler.async_session_factory") as mock_factory,
        ):
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            task = asyncio.create_task(run_heartbeat_checker(interval_seconds=0))
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        # Should have been called at least twice — once errored, once succeeded
        assert call_count >= 2


class TestRemoveOfflineAgents:
    async def test_removes_offline_worktrees(self, db_session: AsyncSession) -> None:
        project = await _create_project(db_session)
        repo = AgentRepository(db_session)
        service = AgentService(repo, BoardRepository(db_session))

        # Register two agents, mark both offline
        await service.register(project.id, "/repo/wt-x", "wt-x")
        await service.register(project.id, "/repo/wt-y", "wt-y")
        worktrees = await repo.get_worktrees_for_project(project.id)
        for wt in worktrees:
            await repo.set_worktree_offline(wt.id)

        count = await service.remove_offline_agents(project.id)
        assert count == 2

        remaining = await repo.get_worktrees_for_project(project.id)
        assert len(remaining) == 0

    async def test_leaves_online_worktrees(self, db_session: AsyncSession) -> None:
        project = await _create_project(db_session)
        repo = AgentRepository(db_session)
        service = AgentService(repo, BoardRepository(db_session))

        await service.register(project.id, "/repo/wt-alive", "wt-alive")
        reg = await service.register(project.id, "/repo/wt-dead", "wt-dead")
        await repo.set_worktree_offline(reg["worktree_id"])

        count = await service.remove_offline_agents(project.id)
        assert count == 1

        remaining = await repo.get_worktrees_for_project(project.id)
        assert len(remaining) == 1
        assert remaining[0].worktree_path == "/repo/wt-alive"

    async def test_returns_zero_when_none_offline(self, db_session: AsyncSession) -> None:
        project = await _create_project(db_session)
        repo = AgentRepository(db_session)
        service = AgentService(repo, BoardRepository(db_session))

        await service.register(project.id, "/repo/wt-active", "wt-active")

        count = await service.remove_offline_agents(project.id)
        assert count == 0


class TestRequestShutdown:
    async def test_request_shutdown_writes_worktree_inbox(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        """request_shutdown writes the JSON shutdown line to <worktree>/.cloglog/inbox."""
        import json

        project = await _create_project(db_session)
        repo = AgentRepository(db_session)
        service = AgentService(repo, BoardRepository(db_session))

        worktree_path = tmp_path / "wt-shutdown"
        worktree_path.mkdir()
        reg = await service.register(project.id, str(worktree_path), "wt-shutdown")
        wt_id = reg["worktree_id"]

        await service.request_shutdown(wt_id)

        inbox_path = worktree_path / ".cloglog" / "inbox"
        assert inbox_path.exists()
        # The legacy path must NOT be used.
        assert not Path(f"/tmp/cloglog-inbox-{wt_id}").exists()

        content = inbox_path.read_text().strip()
        message = json.loads(content)
        assert message["type"] == "shutdown"
        assert "shut down" in message["message"].lower()

    async def test_request_shutdown_creates_inbox_when_missing(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        """request_shutdown creates .cloglog/inbox if the file does not yet exist."""
        project = await _create_project(db_session)
        repo = AgentRepository(db_session)
        service = AgentService(repo, BoardRepository(db_session))

        worktree_path = tmp_path / "wt-fresh"
        worktree_path.mkdir()  # no .cloglog subdir exists yet
        reg = await service.register(project.id, str(worktree_path), "wt-fresh")
        wt_id = reg["worktree_id"]

        inbox_path = worktree_path / ".cloglog" / "inbox"
        assert not inbox_path.exists()
        assert not inbox_path.parent.exists()

        await service.request_shutdown(wt_id)

        assert inbox_path.exists()

    async def test_request_shutdown_appends_does_not_truncate(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        """request_shutdown appends to existing inbox events rather than overwriting."""
        import json

        project = await _create_project(db_session)
        repo = AgentRepository(db_session)
        service = AgentService(repo, BoardRepository(db_session))

        worktree_path = tmp_path / "wt-append"
        worktree_path.mkdir()
        inbox_path = worktree_path / ".cloglog" / "inbox"
        inbox_path.parent.mkdir()
        prior = json.dumps({"type": "pr_merged", "pr_number": 1})
        inbox_path.write_text(prior + "\n")

        reg = await service.register(project.id, str(worktree_path), "wt-append")
        wt_id = reg["worktree_id"]

        await service.request_shutdown(wt_id)

        lines = inbox_path.read_text().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["type"] == "pr_merged"
        assert json.loads(lines[1])["type"] == "shutdown"

    async def test_request_shutdown_sets_db_flag(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        """request_shutdown also sets the shutdown_requested DB flag as fallback."""
        project = await _create_project(db_session)
        repo = AgentRepository(db_session)
        service = AgentService(repo, BoardRepository(db_session))

        worktree_path = tmp_path / "wt-shutdown2"
        worktree_path.mkdir()
        reg = await service.register(project.id, str(worktree_path), "wt-shutdown2")
        wt_id = reg["worktree_id"]

        await service.request_shutdown(wt_id)

        worktree = await repo.get_worktree(wt_id)
        assert worktree is not None
        assert worktree.shutdown_requested is True

    async def test_request_shutdown_rejects_unknown_worktree(
        self, db_session: AsyncSession
    ) -> None:
        """request_shutdown raises ValueError for unknown worktree."""
        await _create_project(db_session)
        repo = AgentRepository(db_session)
        service = AgentService(repo, BoardRepository(db_session))

        with pytest.raises(ValueError, match="not found"):
            await service.request_shutdown(uuid.uuid4())

    async def test_request_shutdown_rejects_missing_worktree_path(
        self, db_session: AsyncSession
    ) -> None:
        """request_shutdown raises a clear error when worktree_path is empty."""
        project = await _create_project(db_session)
        repo = AgentRepository(db_session)
        service = AgentService(repo, BoardRepository(db_session))

        reg = await service.register(project.id, "", "wt-empty-path")
        wt_id = reg["worktree_id"]

        with pytest.raises(ValueError, match="worktree_path"):
            await service.request_shutdown(wt_id)

    async def test_request_shutdown_tail_receives_message(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        """Tailing subprocess observes the shutdown line from request_shutdown."""
        import json

        spawn = asyncio.create_subprocess_exec  # noqa: SLF001 — alias to keep line short

        project = await _create_project(db_session)
        repo = AgentRepository(db_session)
        service = AgentService(repo, BoardRepository(db_session))

        worktree_path = tmp_path / "wt-tail"
        worktree_path.mkdir()
        inbox_dir = worktree_path / ".cloglog"
        inbox_dir.mkdir()
        inbox_path = inbox_dir / "inbox"
        inbox_path.touch()

        reg = await service.register(project.id, str(worktree_path), "wt-tail")
        wt_id = reg["worktree_id"]

        tail_proc = await spawn(
            "tail",
            "-F",
            "-n",
            "0",
            str(inbox_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            # Give tail a beat to attach before we write.
            await asyncio.sleep(0.2)
            await service.request_shutdown(wt_id)

            assert tail_proc.stdout is not None
            line_bytes = await asyncio.wait_for(tail_proc.stdout.readline(), timeout=5.0)
            line = line_bytes.decode().strip()
            msg = json.loads(line)
            assert msg["type"] == "shutdown"
        finally:
            tail_proc.terminate()
            try:
                await asyncio.wait_for(tail_proc.wait(), timeout=2.0)
            except TimeoutError:
                tail_proc.kill()

    async def test_heartbeat_no_longer_returns_shutdown_flag(
        self, db_session: AsyncSession
    ) -> None:
        """Heartbeat response no longer includes shutdown_requested."""
        project = await _create_project(db_session)
        repo = AgentRepository(db_session)
        service = AgentService(repo, BoardRepository(db_session))

        reg = await service.register(project.id, "/repo/wt-hb-shutdown", "wt-hb-shutdown")
        wt_id = reg["worktree_id"]

        result = await service.heartbeat(wt_id)
        assert "shutdown_requested" not in result
        assert result["status"] == "ok"
