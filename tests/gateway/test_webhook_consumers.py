"""Tests for AgentNotifierConsumer — agent resolution, message building, inbox
writing, and PR_MERGED database update.

Covers: pr_url match, branch fallback, no match, message formatting for each
event type, inbox file append, and Task.pr_merged flag update.
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.models import Worktree
from src.agent.repository import AgentRepository
from src.board.models import Epic, Feature, Project, Task
from src.board.repository import BoardRepository
from src.gateway.webhook_consumers import AgentNotifierConsumer
from src.gateway.webhook_dispatcher import WebhookEvent, WebhookEventType

REPO = "sachinkundu/cloglog"
BRANCH = "wt-test-branch"


def _unique_pr_url() -> str:
    return f"https://github.com/sachinkundu/cloglog/pull/{uuid.uuid4().hex[:8]}"


def _make_event(
    event_type: WebhookEventType = WebhookEventType.PR_MERGED,
    pr_url: str = "",
    head_branch: str = BRANCH,
    delivery_id: str = "d-test-1",
    raw: dict[str, Any] | None = None,
) -> WebhookEvent:
    return WebhookEvent(
        type=event_type,
        delivery_id=delivery_id,
        repo_full_name=REPO,
        pr_number=42,
        pr_url=pr_url or _unique_pr_url(),
        head_branch=head_branch,
        base_branch="main",
        sender="sachinkundu",
        raw=raw or {},
    )


async def _seed_project_and_task(
    session: AsyncSession,
    *,
    pr_url: str | None = None,
    branch_name: str = BRANCH,
    task_status: str = "review",
    worktree_status: str = "online",
    worktree_path: str | None = None,
) -> tuple[Project, Task, Worktree]:
    """Create a project, epic, feature, task, and worktree for testing."""
    if pr_url is None:
        pr_url = _unique_pr_url()

    project = Project(
        name=f"test-project-{uuid.uuid4().hex[:6]}",
        description="Test",
        repo_url="https://github.com/sachinkundu/cloglog",
    )
    session.add(project)
    await session.flush()

    epic = Epic(
        project_id=project.id,
        title="Test Epic",
        position=0,
    )
    session.add(epic)
    await session.flush()

    feature = Feature(
        epic_id=epic.id,
        title="Test Feature",
        position=0,
    )
    session.add(feature)
    await session.flush()

    worktree = Worktree(
        project_id=project.id,
        worktree_path=worktree_path or f"/tmp/wt-test-{uuid.uuid4().hex[:6]}",
        branch_name=branch_name,
        status=worktree_status,
    )
    session.add(worktree)
    await session.flush()

    task = Task(
        feature_id=feature.id,
        title="Test Task",
        status=task_status,
        pr_url=pr_url,
        worktree_id=worktree.id,
        position=0,
    )
    session.add(task)
    await session.commit()

    return project, task, worktree


def _make_session_factory(session: AsyncSession):
    """Create a session factory that yields the test session."""

    @asynccontextmanager
    async def factory():
        yield session

    return factory


# ---------------------------------------------------------------------------
# Agent Resolution
# ---------------------------------------------------------------------------


class TestResolveAgent:
    @pytest.mark.asyncio
    async def test_resolve_by_pr_url(self, db_session: AsyncSession) -> None:
        """Primary path: resolve agent via Task.pr_url match."""
        _project, task, worktree = await _seed_project_and_task(db_session)
        consumer = AgentNotifierConsumer()
        event = _make_event(pr_url=task.pr_url)  # type: ignore[arg-type]

        result = await consumer._resolve_agent(event, db_session)
        assert result is not None
        wt_id, wt_path = result
        assert wt_id == worktree.id
        assert wt_path == worktree.worktree_path

    @pytest.mark.asyncio
    async def test_resolve_by_branch_fallback(self, db_session: AsyncSession) -> None:
        """Fallback: when no task has pr_url, resolve via branch name."""
        branch = f"wt-fallback-{uuid.uuid4().hex[:6]}"
        suffix = uuid.uuid4().hex[:6]
        repo_full_name = f"sachinkundu/cloglog-{suffix}"

        project = Project(
            name=f"test-project-{suffix}",
            description="Test",
            repo_url=f"https://github.com/{repo_full_name}",
        )
        db_session.add(project)
        await db_session.flush()

        epic = Epic(project_id=project.id, title="E", position=0)
        db_session.add(epic)
        await db_session.flush()

        feature = Feature(epic_id=epic.id, title="F", position=0)
        db_session.add(feature)
        await db_session.flush()

        worktree = Worktree(
            project_id=project.id,
            worktree_path=f"/tmp/wt-{suffix}",
            branch_name=branch,
            status="online",
        )
        db_session.add(worktree)
        await db_session.flush()

        task = Task(
            feature_id=feature.id,
            title="T",
            status="review",
            pr_url="__NO_MATCH__",
            worktree_id=worktree.id,
            position=0,
        )
        db_session.add(task)
        await db_session.commit()

        event = WebhookEvent(
            type=WebhookEventType.PR_MERGED,
            delivery_id="d-fallback",
            repo_full_name=repo_full_name,
            pr_number=42,
            pr_url=_unique_pr_url(),
            head_branch=branch,
            base_branch="main",
            sender="sachinkundu",
            raw={},
        )
        consumer = AgentNotifierConsumer()

        result = await consumer._resolve_agent(event, db_session)
        assert result is not None
        wt_id, wt_path = result
        assert wt_id == worktree.id
        assert wt_path == worktree.worktree_path

    @pytest.mark.asyncio
    async def test_resolve_no_match(self, db_session: AsyncSession) -> None:
        """No task or worktree matches — returns None."""
        event = _make_event(
            pr_url=_unique_pr_url(),
            head_branch="nonexistent-branch",
        )
        consumer = AgentNotifierConsumer()

        result = await consumer._resolve_agent(event, db_session)
        assert result is None

    @pytest.mark.asyncio
    async def test_resolve_offline_worktree_not_matched_by_branch(
        self, db_session: AsyncSession
    ) -> None:
        """Branch fallback only matches online worktrees."""
        branch = f"wt-offline-{uuid.uuid4().hex[:6]}"
        _project, _task, _worktree = await _seed_project_and_task(
            db_session,
            pr_url="__NO_MATCH__",
            branch_name=branch,
            worktree_status="offline",
        )
        event = _make_event(
            pr_url=_unique_pr_url(),
            head_branch=branch,
        )
        consumer = AgentNotifierConsumer()

        result = await consumer._resolve_agent(event, db_session)
        assert result is None


# ---------------------------------------------------------------------------
# Message Building
# ---------------------------------------------------------------------------


class TestBuildMessage:
    def test_pr_merged_message(self) -> None:
        consumer = AgentNotifierConsumer()
        event = _make_event(event_type=WebhookEventType.PR_MERGED)
        msg = consumer._build_message(event)
        assert msg is not None
        assert msg["type"] == "pr_merged"
        assert msg["pr_number"] == 42
        assert "MERGED" in msg["message"]

    def test_pr_closed_message(self) -> None:
        consumer = AgentNotifierConsumer()
        event = _make_event(event_type=WebhookEventType.PR_CLOSED)
        msg = consumer._build_message(event)
        assert msg is not None
        assert msg["type"] == "pr_closed"
        assert "closed without merging" in msg["message"]

    def test_review_submitted_changes_requested(self) -> None:
        consumer = AgentNotifierConsumer()
        event = _make_event(
            event_type=WebhookEventType.REVIEW_SUBMITTED,
            raw={
                "review": {
                    "state": "changes_requested",
                    "body": "Fix the validation logic",
                },
            },
        )
        msg = consumer._build_message(event)
        assert msg is not None
        assert msg["type"] == "review_submitted"
        assert msg["review_state"] == "changes_requested"
        assert msg["reviewer"] == "sachinkundu"
        assert "Fix the validation logic" in msg["body"]
        assert "Address the feedback" in msg["message"]

    def test_review_submitted_approved(self) -> None:
        consumer = AgentNotifierConsumer()
        event = _make_event(
            event_type=WebhookEventType.REVIEW_SUBMITTED,
            raw={"review": {"state": "approved", "body": "LGTM"}},
        )
        msg = consumer._build_message(event)
        assert msg is not None
        assert msg["review_state"] == "approved"
        assert "Address the feedback" not in msg["message"]

    def test_review_submitted_no_body(self) -> None:
        consumer = AgentNotifierConsumer()
        event = _make_event(
            event_type=WebhookEventType.REVIEW_SUBMITTED,
            raw={"review": {"state": "approved", "body": None}},
        )
        msg = consumer._build_message(event)
        assert msg is not None
        assert msg["body"] == ""
        assert "No comment body" in msg["message"]

    def test_check_run_failure(self) -> None:
        consumer = AgentNotifierConsumer()
        event = _make_event(
            event_type=WebhookEventType.CHECK_RUN_COMPLETED,
            raw={
                "check_run": {
                    "name": "quality",
                    "conclusion": "failure",
                },
            },
        )
        msg = consumer._build_message(event)
        assert msg is not None
        assert msg["type"] == "ci_failed"
        assert msg["check_name"] == "quality"
        assert msg["conclusion"] == "failure"

    def test_check_run_success_returns_none(self) -> None:
        consumer = AgentNotifierConsumer()
        event = _make_event(
            event_type=WebhookEventType.CHECK_RUN_COMPLETED,
            raw={
                "check_run": {
                    "name": "quality",
                    "conclusion": "success",
                },
            },
        )
        msg = consumer._build_message(event)
        assert msg is None

    def test_handles_only_relevant_events(self) -> None:
        consumer = AgentNotifierConsumer()
        # PR_OPENED and PR_SYNCHRONIZE should not be handled
        assert consumer.handles(_make_event(event_type=WebhookEventType.PR_OPENED)) is False
        assert consumer.handles(_make_event(event_type=WebhookEventType.PR_SYNCHRONIZE)) is False
        # These should be handled
        assert consumer.handles(_make_event(event_type=WebhookEventType.PR_MERGED)) is True
        assert consumer.handles(_make_event(event_type=WebhookEventType.PR_CLOSED)) is True
        assert consumer.handles(_make_event(event_type=WebhookEventType.REVIEW_SUBMITTED)) is True
        assert (
            consumer.handles(_make_event(event_type=WebhookEventType.CHECK_RUN_COMPLETED)) is True
        )


# ---------------------------------------------------------------------------
# Inbox File Writing
# ---------------------------------------------------------------------------


class TestInboxWrite:
    @pytest.mark.asyncio
    async def test_inbox_file_appended(self, db_session: AsyncSession, tmp_path: Path) -> None:
        """Verify the consumer appends a JSON line to <worktree_path>/.cloglog/inbox."""
        wt_path = str(tmp_path / "wt-inbox-test")
        Path(wt_path).mkdir()
        _project, task, worktree = await _seed_project_and_task(db_session, worktree_path=wt_path)

        consumer = AgentNotifierConsumer(session_factory=_make_session_factory(db_session))
        event = _make_event(
            event_type=WebhookEventType.PR_MERGED,
            pr_url=task.pr_url,  # type: ignore[arg-type]
        )

        await consumer.handle(event)

        inbox_path = Path(wt_path) / ".cloglog" / "inbox"
        assert inbox_path.exists()
        lines = inbox_path.read_text().strip().split("\n")
        assert len(lines) == 1
        msg = json.loads(lines[0])
        assert msg["type"] == "pr_merged"
        assert msg["pr_number"] == 42

    @pytest.mark.asyncio
    async def test_multiple_events_append_not_overwrite(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        """Multiple events should each append a new line, not overwrite."""
        wt_path = str(tmp_path / "wt-multi-test")
        Path(wt_path).mkdir()
        _project, task, worktree = await _seed_project_and_task(db_session, worktree_path=wt_path)

        consumer = AgentNotifierConsumer(session_factory=_make_session_factory(db_session))

        event1 = _make_event(
            event_type=WebhookEventType.PR_MERGED,
            pr_url=task.pr_url,  # type: ignore[arg-type]
            delivery_id="d-1",
        )
        await consumer.handle(event1)

        event2 = _make_event(
            event_type=WebhookEventType.PR_CLOSED,
            pr_url=task.pr_url,  # type: ignore[arg-type]
            delivery_id="d-2",
        )
        await consumer.handle(event2)

        inbox_path = Path(wt_path) / ".cloglog" / "inbox"
        lines = inbox_path.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["type"] == "pr_merged"
        assert json.loads(lines[1])["type"] == "pr_closed"


# ---------------------------------------------------------------------------
# PR_MERGED Database Update
# ---------------------------------------------------------------------------


class TestPrMergedDbUpdate:
    @pytest.mark.asyncio
    async def test_pr_merged_sets_flag(self, db_session: AsyncSession, tmp_path: Path) -> None:
        """PR_MERGED event should set Task.pr_merged = True in the database."""
        wt_path = str(tmp_path / "wt-merge-test")
        Path(wt_path).mkdir()
        _project, task, worktree = await _seed_project_and_task(db_session, worktree_path=wt_path)
        assert task.pr_merged is False

        consumer = AgentNotifierConsumer(session_factory=_make_session_factory(db_session))
        event = _make_event(
            event_type=WebhookEventType.PR_MERGED,
            pr_url=task.pr_url,  # type: ignore[arg-type]
        )

        await consumer.handle(event)

        await db_session.refresh(task)
        assert task.pr_merged is True

    @pytest.mark.asyncio
    async def test_pr_closed_does_not_set_merged_flag(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        """PR_CLOSED (without merge) should NOT set Task.pr_merged."""
        wt_path = str(tmp_path / "wt-close-test")
        Path(wt_path).mkdir()
        _project, task, worktree = await _seed_project_and_task(db_session, worktree_path=wt_path)
        assert task.pr_merged is False

        consumer = AgentNotifierConsumer(session_factory=_make_session_factory(db_session))
        event = _make_event(
            event_type=WebhookEventType.PR_CLOSED,
            pr_url=task.pr_url,  # type: ignore[arg-type]
        )

        await consumer.handle(event)

        await db_session.refresh(task)
        assert task.pr_merged is False

    @pytest.mark.asyncio
    async def test_pr_merged_updates_db_even_without_agent(self, db_session: AsyncSession) -> None:
        """PR_MERGED should update the DB even if no agent is found for inbox notification."""
        pr_url = _unique_pr_url()
        project = Project(
            name=f"test-no-agent-{uuid.uuid4().hex[:6]}",
            description="Test",
            repo_url="https://github.com/sachinkundu/cloglog",
        )
        db_session.add(project)
        await db_session.flush()

        epic = Epic(project_id=project.id, title="E", position=0)
        db_session.add(epic)
        await db_session.flush()

        feature = Feature(epic_id=epic.id, title="F", position=0)
        db_session.add(feature)
        await db_session.flush()

        task = Task(
            feature_id=feature.id,
            title="T",
            status="review",
            pr_url=pr_url,
            worktree_id=None,  # No agent
            position=0,
        )
        db_session.add(task)
        await db_session.commit()

        consumer = AgentNotifierConsumer(session_factory=_make_session_factory(db_session))
        event = _make_event(event_type=WebhookEventType.PR_MERGED, pr_url=pr_url)

        await consumer.handle(event)

        await db_session.refresh(task)
        assert task.pr_merged is True


# ---------------------------------------------------------------------------
# Repository Methods
# ---------------------------------------------------------------------------


class TestBoardRepositoryPrLookup:
    @pytest.mark.asyncio
    async def test_find_task_by_pr_url(self, db_session: AsyncSession) -> None:
        _project, task, _worktree = await _seed_project_and_task(db_session)
        repo = BoardRepository(db_session)
        found = await repo.find_task_by_pr_url(task.pr_url)  # type: ignore[arg-type]
        assert found is not None
        assert found.id == task.id

    @pytest.mark.asyncio
    async def test_find_task_by_pr_url_no_match(self, db_session: AsyncSession) -> None:
        repo = BoardRepository(db_session)
        found = await repo.find_task_by_pr_url("https://github.com/nobody/nothing/pull/999")
        assert found is None

    @pytest.mark.asyncio
    async def test_find_task_by_pr_url_ignores_done_tasks(self, db_session: AsyncSession) -> None:
        """Tasks in 'done' status should not be found."""
        pr_url = _unique_pr_url()
        _project, task, _worktree = await _seed_project_and_task(
            db_session, task_status="done", pr_url=pr_url
        )
        repo = BoardRepository(db_session)
        found = await repo.find_task_by_pr_url(pr_url)
        assert found is None

    @pytest.mark.asyncio
    async def test_find_project_by_repo(self, db_session: AsyncSession) -> None:
        _project, _task, _worktree = await _seed_project_and_task(db_session)
        repo = BoardRepository(db_session)
        found = await repo.find_project_by_repo("sachinkundu/cloglog")
        assert found is not None
        assert found.repo_url == "https://github.com/sachinkundu/cloglog"

    @pytest.mark.asyncio
    async def test_find_project_by_repo_no_match(self, db_session: AsyncSession) -> None:
        repo = BoardRepository(db_session)
        found = await repo.find_project_by_repo("nonexistent/repo")
        assert found is None


class TestAgentRepositoryBranchLookup:
    @pytest.mark.asyncio
    async def test_get_worktree_by_branch(self, db_session: AsyncSession) -> None:
        branch = f"wt-branch-{uuid.uuid4().hex[:6]}"
        _project, _task, worktree = await _seed_project_and_task(db_session, branch_name=branch)
        repo = AgentRepository(db_session)
        found = await repo.get_worktree_by_branch(_project.id, branch)
        assert found is not None
        assert found.id == worktree.id

    @pytest.mark.asyncio
    async def test_get_worktree_by_branch_no_match(self, db_session: AsyncSession) -> None:
        _project, _task, _worktree = await _seed_project_and_task(db_session)
        repo = AgentRepository(db_session)
        found = await repo.get_worktree_by_branch(_project.id, "nonexistent-branch")
        assert found is None

    @pytest.mark.asyncio
    async def test_get_worktree_by_branch_offline_excluded(self, db_session: AsyncSession) -> None:
        branch = f"wt-offline-{uuid.uuid4().hex[:6]}"
        _project, _task, _worktree = await _seed_project_and_task(
            db_session,
            branch_name=branch,
            worktree_status="offline",
        )
        repo = AgentRepository(db_session)
        found = await repo.get_worktree_by_branch(_project.id, branch)
        assert found is None
