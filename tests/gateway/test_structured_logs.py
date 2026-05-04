"""Pin tests for T-408 structured-event logging.

Invariants:
1. Expected event names exist and produce correct shape (key=value format).
2. Synthetic PR open → 4 codex turns → consensus emits the documented
   sequence and nothing else (one line per state change).
3. Heartbeat tick produces zero log lines (cardinality rule).
4. An unexpected exception in _safe_handle still includes the delivery
   correlation key on the log record (grep-ability invariant).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.gateway.review_engine import ReviewFinding, ReviewResult
from src.gateway.review_loop import ReviewLoop
from src.gateway.webhook_dispatcher import (
    WebhookDispatcher,
    WebhookEvent,
    WebhookEventType,
)
from src.shared.log_event import log_event

# ---------------------------------------------------------------------------
# Re-use the FakeRegistry / StubReviewer from test_review_loop.py
# ---------------------------------------------------------------------------
from tests.gateway.test_review_loop import FakeRegistry, StubReviewer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO = "sachinkundu/cloglog"
_PR_NUM = 314
_PR_URL = f"https://github.com/{_REPO}/pull/{_PR_NUM}"
_HEAD_SHA = "abcdef1234567890"
_PROJECT_ID = uuid.uuid4()
_DELIVERY = "delivery-abc-123"


def _make_event(event_type: WebhookEventType = WebhookEventType.PR_OPENED) -> WebhookEvent:
    return WebhookEvent(
        type=event_type,
        delivery_id=_DELIVERY,
        repo_full_name=_REPO,
        pr_number=_PR_NUM,
        pr_url=_PR_URL,
        head_branch="wt-t314-feature",
        base_branch="main",
        sender="sakundu-claude-assistant[bot]",
        raw={"pull_request": {"head": {"sha": _HEAD_SHA}, "body": "PR body"}},
    )


def _make_loop(
    reviewer: StubReviewer,
    registry: FakeRegistry,
    *,
    stage: str = "codex",
    max_turns: int = 4,
) -> ReviewLoop:
    return ReviewLoop(
        reviewer,
        max_turns=max_turns,
        registry=registry,
        project_id=_PROJECT_ID,
        pr_url=_PR_URL,
        pr_number=_PR_NUM,
        repo_full_name=_REPO,
        head_sha=_HEAD_SHA,
        stage=stage,
        reviewer_token="fake-token",
        session_index=1,
        max_sessions=5,
    )


# ---------------------------------------------------------------------------
# 1. log_event helper produces correct shape
# ---------------------------------------------------------------------------


def test_log_event_shape(caplog: pytest.LogCaptureFixture) -> None:
    """log_event formats lines as ``<name> k1=v1 k2=v2`` with None fields dropped."""
    test_logger = logging.getLogger("test_log_event")
    with caplog.at_level(logging.INFO, logger="test_log_event"):
        log_event(
            test_logger,
            "review.dispatch",
            pr="owner/repo#1",
            sha="abc1234",
            action="enqueue",
            reason=None,
        )

    assert len(caplog.records) == 1
    msg = caplog.records[0].getMessage()
    assert msg.startswith("review.dispatch ")
    assert "pr=owner/repo#1" in msg
    assert "sha=abc1234" in msg
    assert "action=enqueue" in msg
    assert "reason" not in msg  # None fields are omitted


# ---------------------------------------------------------------------------
# 2. Synthetic PR flow → correct ordered event sequence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pr_open_4_turns_consensus_event_sequence(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """PR open → 4 codex turns → consensus emits the documented sequence.

    Expected (codex stage only):
      review.codex pr=... sha=... turn=1 phase=start
      review.persist pr=... sha=... turn=1 result=ok
      review.codex pr=... sha=... turn=1 phase=finish duration_s=...
      ... (turns 2–4 same pattern)
    """

    # Each of turns 1–3 has a NEW finding (distinct file) so predicate (c) keeps
    # the loop running; turn 4 carries status=no_further_concerns (predicate a).
    def _finding(n: int) -> ReviewFinding:
        return ReviewFinding(
            file=f"src/file{n}.py", line=1, severity="low", body="nit", title=f"nit{n}"
        )

    approve = ReviewResult(
        verdict="approve", summary="LGTM", findings=[], status="no_further_concerns"
    )
    responses = [
        (
            ReviewResult(
                verdict="comment",
                summary=f"nit{n}",
                findings=[_finding(n)],
                status=None,
            ),
            1.0,
            False,
        )
        for n in range(1, 4)
    ] + [(approve, 1.0, False)]

    reviewer = StubReviewer(responses=responses)
    registry = FakeRegistry()
    loop = _make_loop(reviewer, registry, max_turns=4)

    review_loop_logger = "src.gateway.review_loop"
    _mock_post = patch(
        "src.gateway.review_loop.post_review",
        new_callable=AsyncMock,
        return_value=True,
    )
    with caplog.at_level(logging.INFO, logger=review_loop_logger), _mock_post:
        outcome = await loop.run(diff="diff --git a/foo.py b/foo.py\n+line")

    assert outcome.consensus_reached
    assert outcome.turns_used == 4

    structured = [
        r for r in caplog.records if r.getMessage().startswith(("review.codex", "review.persist"))
    ]
    pr_key = f"{_REPO}#{_PR_NUM}"

    def _fields(record: logging.LogRecord) -> dict[str, str]:
        parts = record.getMessage().split()
        result: dict[str, str] = {"_name": parts[0]}
        for part in parts[1:]:
            if "=" in part:
                k, v = part.split("=", 1)
                result[k] = v
        return result

    # 4 turns × (start + persist + finish) = 12 structured events
    n_events = len(structured)
    assert n_events == 12, (
        f"expected 12 structured events, got {n_events}: {[r.getMessage() for r in structured]}"
    )

    events = [_fields(r) for r in structured]
    for i, turn in enumerate(range(1, 5)):
        base = i * 3
        assert events[base]["_name"] == "review.codex"
        assert events[base]["phase"] == "start"
        assert events[base]["turn"] == str(turn)
        assert events[base]["pr"] == pr_key

        assert events[base + 1]["_name"] == "review.persist"
        assert events[base + 1]["result"] == "ok"
        assert events[base + 1]["turn"] == str(turn)
        assert events[base + 1]["pr"] == pr_key

        assert events[base + 2]["_name"] == "review.codex"
        assert events[base + 2]["phase"] == "finish"
        assert events[base + 2]["turn"] == str(turn)
        assert "duration_s" in events[base + 2]

    # Correlation key present on every structured line
    for r in structured:
        assert pr_key in r.getMessage(), f"pr key missing: {r.getMessage()}"


# ---------------------------------------------------------------------------
# 3. Heartbeat tick produces zero structured log lines
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_heartbeat_produces_no_structured_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AgentService.heartbeat() produces no INFO log lines (cardinality rule)."""
    from src.agent.services import AgentService

    mock_session = MagicMock()
    mock_session.last_heartbeat = "2026-05-04T00:00:00Z"

    mock_repo = AsyncMock()
    mock_repo.get_active_session.return_value = mock_session
    mock_repo.update_heartbeat.return_value = mock_session

    mock_board_repo = AsyncMock()
    service = AgentService(mock_repo, mock_board_repo)

    with caplog.at_level(logging.INFO, logger="src.agent.services"):
        await service.heartbeat(uuid.uuid4())

    structured = [
        r
        for r in caplog.records
        if any(r.getMessage().startswith(p) for p in ("agent.", "review.", "webhook."))
    ]
    assert structured == [], (
        f"Expected no structured lines, got: {[r.getMessage() for r in structured]}"
    )


# ---------------------------------------------------------------------------
# 4. webhook.dispatched carries delivery correlation key on exception
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_dispatched_error_carries_delivery_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """On consumer exception, webhook.dispatched result=error includes delivery=."""

    class BrokenConsumer:
        def handles(self, event: WebhookEvent) -> bool:
            return True

        async def handle(self, event: WebhookEvent) -> None:
            raise RuntimeError("boom")

    dispatcher = WebhookDispatcher()
    dispatcher.register(BrokenConsumer())
    event = _make_event()

    with caplog.at_level(logging.INFO, logger="src.gateway.webhook_dispatcher"):
        await dispatcher.dispatch(event)
        await asyncio.sleep(0)  # let background task finish

    dispatched = [r for r in caplog.records if "webhook.dispatched" in r.getMessage()]
    assert len(dispatched) >= 1
    dispatched_msg = dispatched[0].getMessage()
    assert f"delivery={_DELIVERY}" in dispatched_msg
    assert "result=error" in dispatched_msg


# ---------------------------------------------------------------------------
# 5. review.dispatch correlation key invariant
# ---------------------------------------------------------------------------


def test_review_dispatch_skip_event_carries_pr_key() -> None:
    """review.dispatch skip events carry pr=<repo>#<num> and sha= when available."""
    import io

    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setLevel(logging.INFO)
    test_logger = logging.getLogger("test_dispatch_key")
    test_logger.addHandler(handler)
    test_logger.setLevel(logging.INFO)

    try:
        log_event(
            test_logger,
            "review.dispatch",
            pr="sachinkundu/cloglog#314",
            sha="abcdef1",
            event="pr_opened",
            action="skip",
            reason="rate_limit",
        )
        line = output.getvalue()
        assert "review.dispatch" in line
        assert "pr=sachinkundu/cloglog#314" in line
        assert "sha=abcdef1" in line
        assert "action=skip" in line
        assert "reason=rate_limit" in line
    finally:
        test_logger.removeHandler(handler)


# ---------------------------------------------------------------------------
# 6. agent.online / agent.task_started events carry wt= key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_online_emits_structured_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """agent.online log line carries wt= correlation key."""
    from src.agent.services import AgentService
    from src.shared.events import event_bus

    mock_worktree = MagicMock()
    mock_worktree.id = uuid.uuid4()
    mock_worktree.project_id = _PROJECT_ID
    mock_worktree.worktree_path = "/home/sachin/code/cloglog/.claude/worktrees/wt-t314-feature"
    mock_worktree.branch_name = "wt-t314-feature"
    mock_worktree.current_task_id = None

    mock_repo = AsyncMock()
    mock_repo.upsert_worktree.return_value = (mock_worktree, True)
    mock_repo.get_active_session.return_value = None
    mock_repo.create_session.return_value = MagicMock(id=uuid.uuid4())
    mock_repo.set_agent_token_hash.return_value = None

    mock_board_repo = AsyncMock()
    service = AgentService(mock_repo, mock_board_repo)

    with (
        caplog.at_level(logging.INFO, logger="src.agent.services"),
        patch.object(event_bus, "publish", new_callable=AsyncMock),
    ):
        await service.register(
            _PROJECT_ID,
            mock_worktree.worktree_path,
            "wt-t314-feature",
        )

    online_records = [r for r in caplog.records if "agent.online" in r.getMessage()]
    assert len(online_records) == 1
    msg = online_records[0].getMessage()
    assert "wt=wt-t314-feature" in msg
    assert f"project={_PROJECT_ID}" in msg


@pytest.mark.asyncio
async def test_agent_task_started_emits_structured_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """agent.task_started log line carries wt= and task=T-NNN."""
    from src.agent.services import AgentService
    from src.shared.events import event_bus

    task_id = uuid.uuid4()
    worktree_id = uuid.uuid4()

    mock_worktree = MagicMock()
    mock_worktree.id = worktree_id
    mock_worktree.project_id = _PROJECT_ID
    mock_worktree.worktree_path = "/home/sachin/code/cloglog/.claude/worktrees/wt-t314-feature"
    mock_worktree.branch_name = "wt-t314-feature"
    mock_worktree.current_task_id = None
    mock_worktree.role = "worktree"

    mock_task = MagicMock()
    mock_task.id = task_id
    mock_task.number = 314
    mock_task.title = "Test feature"
    mock_task.status = "backlog"
    mock_task.task_type = "task"
    mock_task.feature_id = uuid.uuid4()
    mock_task.model = None
    mock_task.pr_merged = False

    mock_repo = AsyncMock()
    mock_repo.get_worktree.return_value = mock_worktree

    mock_board_repo = AsyncMock()
    mock_board_repo.get_task.return_value = mock_task
    mock_board_repo.get_tasks_for_worktree.return_value = []
    mock_board_repo.update_task.return_value = None
    mock_board_repo.get_tasks_for_feature.return_value = []

    mock_blockers = AsyncMock()
    mock_blockers.get_unresolved_blockers.return_value = []
    mock_repo.set_worktree_current_task.return_value = None

    service = AgentService(mock_repo, mock_board_repo, board_blockers=mock_blockers)

    with (
        caplog.at_level(logging.INFO, logger="src.agent.services"),
        patch.object(event_bus, "publish", new_callable=AsyncMock),
    ):
        await service.start_task(worktree_id, task_id)

    task_started = [r for r in caplog.records if "agent.task_started" in r.getMessage()]
    assert len(task_started) == 1
    msg = task_started[0].getMessage()
    assert "wt=wt-t314-feature" in msg
    assert "task=T-314" in msg
