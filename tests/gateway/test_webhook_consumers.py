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
from src.gateway.webhook_consumers import (
    MAIN_AGENT_EVENTS,
    AgentNotifierConsumer,
    ResolvedRecipient,
)
from src.gateway.webhook_dispatcher import WebhookEvent, WebhookEventType
from src.shared.config import settings

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
        assert result.worktree_id == worktree.id
        assert result.inbox_path == Path(worktree.worktree_path) / ".cloglog" / "inbox"

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
        assert result.worktree_id == worktree.id
        assert result.inbox_path == Path(worktree.worktree_path) / ".cloglog" / "inbox"

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
    async def test_resolve_empty_head_branch_returns_none_with_multiple_online_worktrees(
        self, db_session: AsyncSession
    ) -> None:
        """T-254 regression: ``issue_comment`` webhooks arrive with empty
        ``head_branch``. If ``_resolve_agent`` passes that through to the branch
        lookup while multiple online worktrees carry the historical empty
        ``branch_name``, the query matches every one of them and crashes with
        ``MultipleResultsFound``. The resolver must short-circuit and the
        repository must guard the empty case — no crash, return ``None``.
        """
        from sqlalchemy.exc import MultipleResultsFound

        suffix = uuid.uuid4().hex[:6]
        repo_full_name = f"sachinkundu/cloglog-{suffix}"
        project = Project(
            name=f"empty-branch-{suffix}",
            description="T-254 regression",
            repo_url=f"https://github.com/{repo_full_name}",
        )
        db_session.add(project)
        await db_session.flush()

        # Seed THREE online worktrees with empty branch_name — mirrors the
        # pre-fix live-DB state (every row was ``''``).
        for i in range(3):
            db_session.add(
                Worktree(
                    project_id=project.id,
                    worktree_path=f"/tmp/wt-empty-{suffix}-{i}",
                    branch_name="",
                    status="online",
                )
            )
        await db_session.commit()

        event = WebhookEvent(
            type=WebhookEventType.ISSUE_COMMENT,
            delivery_id=f"d-empty-{suffix}",
            repo_full_name=repo_full_name,
            pr_number=42,
            pr_url=_unique_pr_url(),
            head_branch="",  # issue_comment webhooks arrive empty
            base_branch="main",
            sender="sachinkundu",
            raw={"comment": {"body": "LGTM"}},
        )
        consumer = AgentNotifierConsumer()

        # Must NOT raise MultipleResultsFound — that is the crash T-254 fixed.
        try:
            result = await consumer._resolve_agent(event, db_session)
        except MultipleResultsFound:  # pragma: no cover - regression guard
            pytest.fail(
                "_resolve_agent raised MultipleResultsFound on empty head_branch — "
                "T-254 regression: resolver must short-circuit before the branch query."
            )
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

    def test_pr_merged_message_no_get_my_tasks(self) -> None:
        """T-329: pr_merged message must NOT instruct agents to call get_my_tasks.

        The backend-generated inbox message is the runtime signal agents act on.
        If it still says 'call get_my_tasks and start the next task', agents
        will follow the old multi-task loop even if the docs say otherwise.
        The T-329 contract requires the message to describe the per-task
        shutdown sequence instead.
        """
        consumer = AgentNotifierConsumer()
        event = _make_event(event_type=WebhookEventType.PR_MERGED)
        msg = consumer._build_message(event)
        assert msg is not None
        assert "get_my_tasks and start the next task" not in msg["message"], (
            "pr_merged inbox message must not contain 'get_my_tasks and start the next task'. "
            "T-329 replaces the multi-task loop with a per-task shutdown sequence. "
            "The supervisor handles relaunching for subsequent tasks."
        )
        assert "unregister_agent" in msg["message"], (
            "pr_merged inbox message must instruct agents to call unregister_agent "
            "as part of the T-329 per-task shutdown sequence."
        )

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

    def test_issue_comment_message(self) -> None:
        consumer = AgentNotifierConsumer()
        event = _make_event(
            event_type=WebhookEventType.ISSUE_COMMENT,
            raw={
                "comment": {
                    "body": "Looks good to me, just fix the typo.",
                },
            },
        )
        msg = consumer._build_message(event)
        assert msg is not None
        assert msg["type"] == "issue_comment"
        assert msg["pr_number"] == 42
        assert msg["commenter"] == "sachinkundu"
        assert "Looks good to me" in msg["body"]
        assert "sachinkundu" in msg["message"]

    def test_issue_comment_no_body(self) -> None:
        consumer = AgentNotifierConsumer()
        event = _make_event(
            event_type=WebhookEventType.ISSUE_COMMENT,
            raw={"comment": {"body": None}},
        )
        msg = consumer._build_message(event)
        assert msg is not None
        assert msg["body"] == ""

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

    def test_check_run_null_conclusion_returns_none(self) -> None:
        """GitHub fires check_run with null conclusion before the check terminates.

        The consumer must not treat a pending check as a failure — the former
        behavior caused false ci_failed notifications on every queued check.
        """
        consumer = AgentNotifierConsumer()
        event = _make_event(
            event_type=WebhookEventType.CHECK_RUN_COMPLETED,
            raw={
                "check_run": {
                    "name": "quality",
                    "conclusion": None,
                },
            },
        )
        msg = consumer._build_message(event)
        assert msg is None

    def test_check_run_missing_conclusion_returns_none(self) -> None:
        """A check_run payload without a conclusion key must be treated as pending."""
        consumer = AgentNotifierConsumer()
        event = _make_event(
            event_type=WebhookEventType.CHECK_RUN_COMPLETED,
            raw={"check_run": {"name": "quality"}},
        )
        msg = consumer._build_message(event)
        assert msg is None

    def test_check_run_neutral_returns_none(self) -> None:
        """neutral is a terminal non-failure conclusion — do not notify."""
        consumer = AgentNotifierConsumer()
        event = _make_event(
            event_type=WebhookEventType.CHECK_RUN_COMPLETED,
            raw={"check_run": {"name": "quality", "conclusion": "neutral"}},
        )
        msg = consumer._build_message(event)
        assert msg is None

    def test_check_run_skipped_returns_none(self) -> None:
        """skipped is a terminal non-failure conclusion — do not notify."""
        consumer = AgentNotifierConsumer()
        event = _make_event(
            event_type=WebhookEventType.CHECK_RUN_COMPLETED,
            raw={"check_run": {"name": "quality", "conclusion": "skipped"}},
        )
        msg = consumer._build_message(event)
        assert msg is None

    @pytest.mark.parametrize(
        "conclusion",
        ["failure", "cancelled", "timed_out", "action_required", "stale"],
    )
    def test_check_run_non_success_terminal_emits_ci_failed(self, conclusion: str) -> None:
        """All non-success terminal conclusions should emit ci_failed."""
        consumer = AgentNotifierConsumer()
        event = _make_event(
            event_type=WebhookEventType.CHECK_RUN_COMPLETED,
            raw={"check_run": {"name": "quality", "conclusion": conclusion}},
        )
        msg = consumer._build_message(event)
        assert msg is not None
        assert msg["type"] == "ci_failed"
        assert msg["conclusion"] == conclusion

    def test_review_comment_message(self) -> None:
        consumer = AgentNotifierConsumer()
        event = _make_event(
            event_type=WebhookEventType.REVIEW_COMMENT,
            raw={
                "comment": {
                    "body": "This needs a None check",
                    "path": "src/gateway/webhook_consumers.py",
                    "line": 42,
                },
            },
        )
        msg = consumer._build_message(event)
        assert msg is not None
        assert msg["type"] == "review_comment"
        assert msg["reviewer"] == "sachinkundu"
        assert msg["path"] == "src/gateway/webhook_consumers.py"
        assert msg["line"] == 42
        assert "This needs a None check" in msg["body"]
        assert "webhook_consumers.py:42" in msg["message"]

    def test_handles_only_relevant_events(self) -> None:
        consumer = AgentNotifierConsumer()
        # PR_OPENED and PR_SYNCHRONIZE should not be handled
        assert consumer.handles(_make_event(event_type=WebhookEventType.PR_OPENED)) is False
        assert consumer.handles(_make_event(event_type=WebhookEventType.PR_SYNCHRONIZE)) is False
        # These should be handled
        assert consumer.handles(_make_event(event_type=WebhookEventType.PR_MERGED)) is True
        assert consumer.handles(_make_event(event_type=WebhookEventType.PR_CLOSED)) is True
        assert consumer.handles(_make_event(event_type=WebhookEventType.REVIEW_SUBMITTED)) is True
        assert consumer.handles(_make_event(event_type=WebhookEventType.REVIEW_COMMENT)) is True
        assert consumer.handles(_make_event(event_type=WebhookEventType.ISSUE_COMMENT)) is True
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
    async def test_check_run_null_conclusion_writes_nothing(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        """End-to-end: a pending check_run event must not touch the inbox file."""
        wt_path = str(tmp_path / "wt-null-conclusion")
        Path(wt_path).mkdir()
        _project, task, _worktree = await _seed_project_and_task(db_session, worktree_path=wt_path)

        consumer = AgentNotifierConsumer(session_factory=_make_session_factory(db_session))
        event = _make_event(
            event_type=WebhookEventType.CHECK_RUN_COMPLETED,
            pr_url=task.pr_url,  # type: ignore[arg-type]
            raw={"check_run": {"name": "quality", "conclusion": None}},
        )

        await consumer.handle(event)

        inbox_path = Path(wt_path) / ".cloglog" / "inbox"
        assert not inbox_path.exists()

    @pytest.mark.asyncio
    async def test_check_run_failure_writes_inbox(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        """End-to-end: a failure check_run event must append a ci_failed line."""
        wt_path = str(tmp_path / "wt-ci-failure")
        Path(wt_path).mkdir()
        _project, task, _worktree = await _seed_project_and_task(db_session, worktree_path=wt_path)

        consumer = AgentNotifierConsumer(session_factory=_make_session_factory(db_session))
        event = _make_event(
            event_type=WebhookEventType.CHECK_RUN_COMPLETED,
            pr_url=task.pr_url,  # type: ignore[arg-type]
            raw={"check_run": {"name": "quality", "conclusion": "failure"}},
        )

        await consumer.handle(event)

        inbox_path = Path(wt_path) / ".cloglog" / "inbox"
        assert inbox_path.exists()
        msg = json.loads(inbox_path.read_text().strip())
        assert msg["type"] == "ci_failed"
        assert msg["conclusion"] == "failure"
        assert msg["check_name"] == "quality"

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
    async def test_get_worktree_by_branch_empty_string_returns_none(
        self, db_session: AsyncSession
    ) -> None:
        """T-254 regression: an equality match on ``branch_name=''`` used to fan
        out across every legacy row whose branch was never populated and raise
        ``MultipleResultsFound``. The defensive guard short-circuits that.
        """
        from sqlalchemy.exc import MultipleResultsFound

        suffix = uuid.uuid4().hex[:6]
        project = Project(
            name=f"empty-branch-repo-{suffix}",
            description="T-254",
            repo_url=f"https://github.com/sachinkundu/empty-{suffix}",
        )
        db_session.add(project)
        await db_session.flush()
        for i in range(2):
            db_session.add(
                Worktree(
                    project_id=project.id,
                    worktree_path=f"/tmp/wt-empty-repo-{suffix}-{i}",
                    branch_name="",
                    status="online",
                )
            )
        await db_session.commit()

        repo = AgentRepository(db_session)
        try:
            found = await repo.get_worktree_by_branch(project.id, "")
        except MultipleResultsFound:  # pragma: no cover - regression guard
            pytest.fail(
                "get_worktree_by_branch raised MultipleResultsFound on empty "
                "branch_name — T-254 regression: guard must short-circuit."
            )
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


# ---------------------------------------------------------------------------
# T-245 Main-Agent Fallback (role-based)
# ---------------------------------------------------------------------------


async def _seed_main_agent_worktree(
    session: AsyncSession, project_id: uuid.UUID, *, worktree_path: str, status: str = "online"
) -> Worktree:
    """Insert a ``role='main'`` worktree row for ``project_id``."""
    worktree = Worktree(
        project_id=project_id,
        worktree_path=worktree_path,
        branch_name="",
        status=status,
        role="main",
    )
    session.add(worktree)
    await session.commit()
    await session.refresh(worktree)
    return worktree


async def _seed_isolated_project(
    session: AsyncSession, *, suffix: str | None = None
) -> tuple[Project, str]:
    """Create a Project with a unique ``repo_url`` so ``find_project_by_repo``
    is unambiguous within a test that exercises the resolver. Returns the
    project and the matching ``repo_full_name`` for use in the ``WebhookEvent``.
    """
    s = suffix or uuid.uuid4().hex[:8]
    repo_full_name = f"sachinkundu/cloglog-{s}"
    project = Project(
        name=f"t245-{s}",
        description="T-245",
        repo_url=f"https://github.com/{repo_full_name}",
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return project, repo_full_name


class TestMainAgentFallback:
    """T-245: route unmatched PRs to the project's main-agent worktree.

    The resolution order is (1) ``Task.pr_url``, (2) ``Worktree.branch_name``,
    (3) ``Worktree.role='main'`` for the project. ISSUE_COMMENT is excluded
    from the fallback to avoid bot spam landing in the main inbox. PRs from
    foreign repos short-circuit at the project lookup so they cannot leak
    into another project's main inbox.
    """

    @pytest.mark.asyncio
    async def test_resolver_returns_main_agent_when_role_set_and_all_lookups_miss(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        """Tertiary fallback returns the role='main' worktree when both prior
        lookups miss. This is the critical path for main-agent-authored PRs and
        close-wave PRs whose branch has no registered worktree row.
        """
        project, repo_full_name = await _seed_isolated_project(db_session)
        main_path = str(tmp_path / "main-clone")
        main = await _seed_main_agent_worktree(db_session, project.id, worktree_path=main_path)

        event = _make_event(
            event_type=WebhookEventType.PR_MERGED,
            pr_url=_unique_pr_url(),
            head_branch="wt-close-no-match",
        )
        event = WebhookEvent(**{**event.__dict__, "repo_full_name": repo_full_name})
        consumer = AgentNotifierConsumer()

        result = await consumer._resolve_agent(event, db_session)

        assert result is not None
        assert isinstance(result, ResolvedRecipient)
        assert result.worktree_id == main.id
        assert result.inbox_path == Path(main_path) / ".cloglog" / "inbox"

    @pytest.mark.asyncio
    async def test_resolver_returns_none_when_no_main_agent_registered(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Acceptance: a project with no main-agent worktree AND no legacy
        ``main_agent_inbox_path`` configured → DEBUG log + drop.

        The project exists (``find_project_by_repo`` succeeds) but no row carries
        ``role='main'`` and the env-var compat fallback is not configured, so
        the resolver returns ``None`` — same outcome as the pre-T-253 baseline.
        """
        monkeypatch.setattr(settings, "main_agent_inbox_path", None)
        _project, repo_full_name = await _seed_isolated_project(db_session)

        event = _make_event(
            event_type=WebhookEventType.PR_MERGED,
            pr_url=_unique_pr_url(),
            head_branch="wt-close-no-match",
        )
        event = WebhookEvent(**{**event.__dict__, "repo_full_name": repo_full_name})
        consumer = AgentNotifierConsumer()

        result = await consumer._resolve_agent(event, db_session)

        assert result is None

    @pytest.mark.asyncio
    async def test_resolver_picks_earliest_when_multiple_main_agents(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        """Acceptance: two ``role='main'`` rows → pick deterministically by
        earliest ``created_at``. ``get_main_agent_worktree`` also logs a warning;
        we don't assert the log line here but the deterministic pick is required.
        """
        project, repo_full_name = await _seed_isolated_project(db_session)
        first = await _seed_main_agent_worktree(
            db_session, project.id, worktree_path=str(tmp_path / "main-first")
        )
        # Second main row created strictly after the first so created_at differs.
        await _seed_main_agent_worktree(
            db_session, project.id, worktree_path=str(tmp_path / "main-second")
        )

        event = _make_event(
            event_type=WebhookEventType.PR_MERGED,
            pr_url=_unique_pr_url(),
            head_branch="wt-no-match",
        )
        event = WebhookEvent(**{**event.__dict__, "repo_full_name": repo_full_name})
        consumer = AgentNotifierConsumer()

        result = await consumer._resolve_agent(event, db_session)

        assert result is not None
        assert result.worktree_id == first.id

    @pytest.mark.asyncio
    async def test_handle_appends_json_to_main_agent_inbox_when_lookups_miss(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        """End-to-end: handle() writes the JSON line to the main agent's
        ``<worktree_path>/.cloglog/inbox`` when both prior lookups miss.
        """
        main_dir = tmp_path / "main-clone"
        main_dir.mkdir()
        project, repo_full_name = await _seed_isolated_project(db_session)
        await _seed_main_agent_worktree(db_session, project.id, worktree_path=str(main_dir))

        event = _make_event(
            event_type=WebhookEventType.PR_MERGED,
            pr_url=_unique_pr_url(),
            head_branch="wt-close-foo",
        )
        event = WebhookEvent(**{**event.__dict__, "repo_full_name": repo_full_name})
        consumer = AgentNotifierConsumer(session_factory=_make_session_factory(db_session))

        await consumer.handle(event)

        main_inbox = main_dir / ".cloglog" / "inbox"
        assert main_inbox.exists(), "Main-agent inbox must be created by handle()"
        lines = main_inbox.read_text().strip().split("\n")
        assert len(lines) == 1
        msg = json.loads(lines[0])
        assert msg["type"] == "pr_merged"

    @pytest.mark.asyncio
    async def test_worktree_still_routed_to_own_inbox_when_pr_url_matches(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        """Acceptance: when ``Task.pr_url`` matches, the task path wins and the
        main-agent fallback must NOT fire — registering a main agent must not
        intercept events that already have a registered owner.
        """
        wt_dir = tmp_path / "wt-real"
        wt_dir.mkdir()
        main_dir = tmp_path / "main-clone"
        main_dir.mkdir()
        project, task, _worktree = await _seed_project_and_task(
            db_session, worktree_path=str(wt_dir)
        )
        await _seed_main_agent_worktree(db_session, project.id, worktree_path=str(main_dir))

        event = _make_event(
            event_type=WebhookEventType.PR_MERGED,
            pr_url=task.pr_url,  # type: ignore[arg-type]
        )
        consumer = AgentNotifierConsumer(session_factory=_make_session_factory(db_session))

        await consumer.handle(event)

        worktree_inbox = wt_dir / ".cloglog" / "inbox"
        assert worktree_inbox.exists()
        msg = json.loads(worktree_inbox.read_text().strip())
        assert msg["type"] == "pr_merged"
        assert not (main_dir / ".cloglog" / "inbox").exists(), (
            "Main-agent inbox must NOT be written when a worktree owns the PR"
        )

    @pytest.mark.asyncio
    async def test_issue_comment_does_not_reach_main_agent(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        """ISSUE_COMMENT must NOT fall back to the main-agent inbox even when a
        main-agent worktree exists — bot spam would overwhelm it. The event type
        is deliberately excluded from ``MAIN_AGENT_EVENTS``.
        """
        project, repo_full_name = await _seed_isolated_project(db_session)
        await _seed_main_agent_worktree(
            db_session, project.id, worktree_path=str(tmp_path / "main-clone")
        )

        event = _make_event(
            event_type=WebhookEventType.ISSUE_COMMENT,
            pr_url=_unique_pr_url(),
            head_branch="",  # issue_comment arrives with empty head_branch
            raw={"comment": {"body": "bot spam"}},
        )
        event = WebhookEvent(**{**event.__dict__, "repo_full_name": repo_full_name})
        consumer = AgentNotifierConsumer()

        result = await consumer._resolve_agent(event, db_session)

        assert result is None, (
            "ISSUE_COMMENT must not be routed to main agent; "
            f"MAIN_AGENT_EVENTS={MAIN_AGENT_EVENTS!r}"
        )

    @pytest.mark.asyncio
    async def test_legacy_settings_path_used_when_no_main_role_row(
        self,
        db_session: AsyncSession,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """T-253 compatibility: when no ``role='main'`` row is registered yet but
        ``settings.main_agent_inbox_path`` IS configured, the resolver falls
        through to that file path. Without this chain, an operator who set the
        documented env var but has not yet run ``/cloglog setup`` (the manual
        step that registers the main agent) would lose unmatched PR events.
        """
        legacy_inbox = tmp_path / "legacy-main-inbox"
        monkeypatch.setattr(settings, "main_agent_inbox_path", legacy_inbox)
        _project, repo_full_name = await _seed_isolated_project(db_session)

        event = _make_event(
            event_type=WebhookEventType.PR_MERGED,
            pr_url=_unique_pr_url(),
            head_branch="wt-no-match",
        )
        event = WebhookEvent(**{**event.__dict__, "repo_full_name": repo_full_name})
        consumer = AgentNotifierConsumer()

        result = await consumer._resolve_agent(event, db_session)

        assert result is not None
        assert result.inbox_path == legacy_inbox
        assert result.worktree_id is None

    @pytest.mark.asyncio
    async def test_role_main_takes_precedence_over_legacy_settings_path(
        self,
        db_session: AsyncSession,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When BOTH a ``role='main'`` row exists AND the legacy
        ``main_agent_inbox_path`` is set, the role-based path wins — the
        registered worktree is the source of truth.
        """
        legacy_inbox = tmp_path / "legacy-main-inbox"
        monkeypatch.setattr(settings, "main_agent_inbox_path", legacy_inbox)
        project, repo_full_name = await _seed_isolated_project(db_session)
        main_path = str(tmp_path / "registered-main")
        main = await _seed_main_agent_worktree(db_session, project.id, worktree_path=main_path)

        event = _make_event(
            event_type=WebhookEventType.PR_MERGED,
            pr_url=_unique_pr_url(),
            head_branch="wt-no-match",
        )
        event = WebhookEvent(**{**event.__dict__, "repo_full_name": repo_full_name})
        consumer = AgentNotifierConsumer()

        result = await consumer._resolve_agent(event, db_session)

        assert result is not None
        assert result.worktree_id == main.id
        assert result.inbox_path == Path(main_path) / ".cloglog" / "inbox"

    @pytest.mark.asyncio
    async def test_unknown_repo_does_not_reach_main_agent(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        """A signed webhook for a repo NOT registered as a cloglog project must
        not fall through to any project's main-agent inbox. The resolver short-
        circuits at ``find_project_by_repo`` before the role lookup runs.
        """
        project, _ = await _seed_isolated_project(db_session)
        await _seed_main_agent_worktree(
            db_session, project.id, worktree_path=str(tmp_path / "main-clone")
        )

        foreign_repo = f"someone-else/unrelated-{uuid.uuid4().hex[:6]}"
        event = WebhookEvent(
            type=WebhookEventType.PR_MERGED,
            delivery_id=f"d-foreign-{uuid.uuid4().hex[:6]}",
            repo_full_name=foreign_repo,
            pr_number=999,
            pr_url=_unique_pr_url(),
            head_branch="wt-close-foreign",
            base_branch="main",
            sender="nobody",
            raw={},
        )
        consumer = AgentNotifierConsumer()

        result = await consumer._resolve_agent(event, db_session)

        assert result is None


class TestGetMainAgentWorktree:
    """Repository-level tests for ``AgentRepository.get_main_agent_worktree``."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_main_role_row(self, db_session: AsyncSession) -> None:
        project, _task, _worktree = await _seed_project_and_task(
            db_session, pr_url=_unique_pr_url()
        )
        agent_repo = AgentRepository(db_session)
        assert await agent_repo.get_main_agent_worktree(project.id) is None

    @pytest.mark.asyncio
    async def test_returns_main_role_row(self, db_session: AsyncSession, tmp_path: Path) -> None:
        project, _task, _worktree = await _seed_project_and_task(
            db_session, pr_url=_unique_pr_url()
        )
        main = await _seed_main_agent_worktree(
            db_session, project.id, worktree_path=str(tmp_path / "main")
        )
        agent_repo = AgentRepository(db_session)
        found = await agent_repo.get_main_agent_worktree(project.id)
        assert found is not None
        assert found.id == main.id

    @pytest.mark.asyncio
    async def test_ignores_offline_status_filter(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        """An offline main agent must still be findable — the inbox file lives
        on disk regardless of process state.
        """
        project, _task, _worktree = await _seed_project_and_task(
            db_session, pr_url=_unique_pr_url()
        )
        main = await _seed_main_agent_worktree(
            db_session,
            project.id,
            worktree_path=str(tmp_path / "main"),
            status="offline",
        )
        agent_repo = AgentRepository(db_session)
        found = await agent_repo.get_main_agent_worktree(project.id)
        assert found is not None
        assert found.id == main.id


class TestRegisterDerivesRole:
    """``register`` derives ``worktrees.role`` from the path: rows under a
    ``/.claude/worktrees/`` segment are ``worktree``; everything else is
    ``main``. This is the source of truth for the webhook fallback.
    """

    @pytest.mark.asyncio
    async def test_repo_root_path_gets_main_role(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        from src.agent.services import AgentService
        from src.board.repository import BoardRepository as _BoardRepo

        project = Project(
            name=f"role-main-{uuid.uuid4().hex[:6]}",
            description="T-245",
            repo_url="https://github.com/sachinkundu/role-main",
        )
        db_session.add(project)
        await db_session.commit()

        service = AgentService(AgentRepository(db_session), _BoardRepo(db_session))
        main_path = str(tmp_path / "main-clone")
        await service.register(project.id, main_path, branch_name="main")

        repo = AgentRepository(db_session)
        wt = await repo.get_worktree_by_path(project.id, main_path)
        assert wt is not None
        assert wt.role == "main"

    @pytest.mark.asyncio
    async def test_sandboxed_worktree_path_gets_worktree_role(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        from src.agent.services import AgentService
        from src.board.repository import BoardRepository as _BoardRepo

        project = Project(
            name=f"role-wt-{uuid.uuid4().hex[:6]}",
            description="T-245",
            repo_url="https://github.com/sachinkundu/role-wt",
        )
        db_session.add(project)
        await db_session.commit()

        service = AgentService(AgentRepository(db_session), _BoardRepo(db_session))
        wt_path = f"{tmp_path}/.claude/worktrees/wt-role-test"
        Path(wt_path).mkdir(parents=True)
        await service.register(project.id, wt_path, branch_name="wt-role-test")

        repo = AgentRepository(db_session)
        wt = await repo.get_worktree_by_path(project.id, wt_path)
        assert wt is not None
        assert wt.role == "worktree"
