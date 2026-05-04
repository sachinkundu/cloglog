"""T-409: Table-driven pin tests for the codex status projection.

Each row constructs synthetic pr_review_turn rows and a head_sha,
then asserts that ``ReviewTurnRepository.codex_status_by_pr`` returns
the expected ``CodexStatus``.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.board.models import Project
from src.review.interfaces import CodexProgress, CodexStatus, CodexStatusResult
from src.review.models import PrReviewTurn
from src.review.repository import ReviewTurnRepository


async def _make_project(session: AsyncSession) -> UUID:
    project = Project(name=f"codex-status-test-{uuid4().hex[:8]}")
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return project.id


async def _status(
    session: AsyncSession,
    project_id: UUID,
    pr_url: str,
    head_sha: str,
    turns: list[PrReviewTurn],
    max_turns: int = 1,
) -> CodexStatusResult:
    for turn in turns:
        session.add(turn)
    await session.commit()

    repo = ReviewTurnRepository(session)
    result = await repo.codex_status_by_pr(
        project_id=project_id,
        pr_url_to_head_sha={pr_url: head_sha},
        max_turns=max_turns,
    )
    return result[pr_url]


@pytest.fixture()
async def project_id(db_session: AsyncSession) -> UUID:
    return await _make_project(db_session)


async def test_not_started_no_turns(db_session: AsyncSession, project_id: UUID) -> None:
    """No turn rows at all → NOT_STARTED."""
    result = await _status(
        db_session, project_id, "https://github.com/o/r/pull/1", "a" * 40, turns=[]
    )
    assert result.status == CodexStatus.NOT_STARTED
    assert result.progress is None


async def test_not_started_empty_sha(db_session: AsyncSession, project_id: UUID) -> None:
    """Empty head_sha (task has no stored sha yet) → NOT_STARTED."""
    pr_url = "https://github.com/o/r/pull/2"
    turns = [
        PrReviewTurn(
            project_id=project_id,
            pr_url=pr_url,
            pr_number=2,
            head_sha="a" * 40,
            stage="codex",
            turn_number=1,
            status="completed",
            consensus_reached=True,
        )
    ]
    result = await _status(db_session, project_id, pr_url, "", turns)
    assert result.status == CodexStatus.NOT_STARTED


async def test_working_running_turn(db_session: AsyncSession, project_id: UUID) -> None:
    """A running turn for the current sha → WORKING."""
    pr_url = "https://github.com/o/r/pull/3"
    sha = "b" * 40
    turns = [
        PrReviewTurn(
            project_id=project_id,
            pr_url=pr_url,
            pr_number=3,
            head_sha=sha,
            stage="codex",
            turn_number=1,
            status="running",
            consensus_reached=False,
        )
    ]
    result = await _status(db_session, project_id, pr_url, sha, turns)
    assert result.status == CodexStatus.WORKING
    assert result.progress is None


async def test_pass_consensus(db_session: AsyncSession, project_id: UUID) -> None:
    """Completed turn with consensus_reached=True → PASS."""
    pr_url = "https://github.com/o/r/pull/4"
    sha = "c" * 40
    turns = [
        PrReviewTurn(
            project_id=project_id,
            pr_url=pr_url,
            pr_number=4,
            head_sha=sha,
            stage="codex",
            turn_number=1,
            status="completed",
            consensus_reached=True,
        )
    ]
    result = await _status(db_session, project_id, pr_url, sha, turns)
    assert result.status == CodexStatus.PASS
    assert result.progress is None


async def test_exhausted_max_turns_no_consensus(db_session: AsyncSession, project_id: UUID) -> None:
    """N completed turns, no consensus, N >= max_turns → EXHAUSTED."""
    pr_url = "https://github.com/o/r/pull/5"
    sha = "d" * 40
    turns = [
        PrReviewTurn(
            project_id=project_id,
            pr_url=pr_url,
            pr_number=5,
            head_sha=sha,
            stage="codex",
            turn_number=i,
            status="completed",
            consensus_reached=False,
        )
        for i in range(1, 4)  # 3 turns
    ]
    result = await _status(db_session, project_id, pr_url, sha, turns, max_turns=3)
    assert result.status == CodexStatus.EXHAUSTED
    assert result.progress is None


async def test_failed_timed_out(db_session: AsyncSession, project_id: UUID) -> None:
    """A timed_out turn for the current sha → FAILED."""
    pr_url = "https://github.com/o/r/pull/6"
    sha = "e" * 40
    turns = [
        PrReviewTurn(
            project_id=project_id,
            pr_url=pr_url,
            pr_number=6,
            head_sha=sha,
            stage="codex",
            turn_number=1,
            status="timed_out",
            consensus_reached=False,
        )
    ]
    result = await _status(db_session, project_id, pr_url, sha, turns)
    assert result.status == CodexStatus.FAILED


async def test_failed_status(db_session: AsyncSession, project_id: UUID) -> None:
    """A failed turn for the current sha → FAILED."""
    pr_url = "https://github.com/o/r/pull/7"
    sha = "f" * 40
    turns = [
        PrReviewTurn(
            project_id=project_id,
            pr_url=pr_url,
            pr_number=7,
            head_sha=sha,
            stage="codex",
            turn_number=1,
            status="failed",
            consensus_reached=False,
        )
    ]
    result = await _status(db_session, project_id, pr_url, sha, turns)
    assert result.status == CodexStatus.FAILED


async def test_progress_some_completed_not_max(db_session: AsyncSession, project_id: UUID) -> None:
    """N completed turns, no consensus, N < max_turns → PROGRESS with correct counts."""
    pr_url = "https://github.com/o/r/pull/8"
    sha = "1a" * 20
    turns = [
        PrReviewTurn(
            project_id=project_id,
            pr_url=pr_url,
            pr_number=8,
            head_sha=sha,
            stage="codex",
            turn_number=1,
            status="completed",
            consensus_reached=False,
        )
    ]
    result = await _status(db_session, project_id, pr_url, sha, turns, max_turns=3)
    assert result.status == CodexStatus.PROGRESS
    assert result.progress == CodexProgress(turn=1, max_turns=3, sha=sha)


async def test_stale_push_no_pickup(db_session: AsyncSession, project_id: UUID) -> None:
    """Old sha has turns but current sha has none → STALE."""
    pr_url = "https://github.com/o/r/pull/9"
    old_sha = "2b" * 20
    new_sha = "3c" * 20
    turns = [
        PrReviewTurn(
            project_id=project_id,
            pr_url=pr_url,
            pr_number=9,
            head_sha=old_sha,
            stage="codex",
            turn_number=1,
            status="completed",
            consensus_reached=True,
        )
    ]
    result = await _status(db_session, project_id, pr_url, new_sha, turns)
    assert result.status == CodexStatus.STALE


async def test_opencode_turns_ignored(db_session: AsyncSession, project_id: UUID) -> None:
    """Opencode turns do NOT affect codex status — only stage='codex' counts."""
    pr_url = "https://github.com/o/r/pull/10"
    sha = "4d" * 20
    turns = [
        PrReviewTurn(
            project_id=project_id,
            pr_url=pr_url,
            pr_number=10,
            head_sha=sha,
            stage="opencode",
            turn_number=1,
            status="running",
            consensus_reached=False,
        )
    ]
    result = await _status(db_session, project_id, pr_url, sha, turns)
    assert result.status == CodexStatus.NOT_STARTED


async def test_cross_project_isolation(db_session: AsyncSession) -> None:
    """Turns for project A must not affect codex_status for project B with same pr_url."""
    pr_url = "https://github.com/o/r/pull/11"
    sha = "5e" * 20
    project_a = await _make_project(db_session)
    project_b = await _make_project(db_session)

    db_session.add(
        PrReviewTurn(
            project_id=project_a,
            pr_url=pr_url,
            pr_number=11,
            head_sha=sha,
            stage="codex",
            turn_number=1,
            status="completed",
            consensus_reached=True,
        )
    )
    await db_session.commit()

    repo = ReviewTurnRepository(db_session)
    result_a = await repo.codex_status_by_pr(
        project_id=project_a,
        pr_url_to_head_sha={pr_url: sha},
        max_turns=1,
    )
    result_b = await repo.codex_status_by_pr(
        project_id=project_b,
        pr_url_to_head_sha={pr_url: sha},
        max_turns=1,
    )
    assert result_a[pr_url].status == CodexStatus.PASS
    assert result_b[pr_url].status == CodexStatus.NOT_STARTED


async def test_empty_input_returns_empty(db_session: AsyncSession) -> None:
    """Empty pr_url_to_head_sha input returns empty dict without a DB round-trip."""
    repo = ReviewTurnRepository(db_session)
    result = await repo.codex_status_by_pr(
        project_id=uuid4(),
        pr_url_to_head_sha={},
        max_turns=1,
    )
    assert result == {}


async def test_board_endpoint_carries_codex_status(
    client: object, db_session: AsyncSession
) -> None:
    """Board endpoint returns codex_status and codex_progress on each TaskCard."""
    from httpx import AsyncClient
    from sqlalchemy import select as sa_select

    from src.board.models import Task

    assert isinstance(client, AsyncClient)

    pr_url = f"https://github.com/o/r/pull/{uuid4().hex[:4]}"
    sha = "6f" * 20

    project = (await client.post("/api/v1/projects", json={"name": f"cs-{uuid4().hex[:6]}"})).json()
    epic = (
        await client.post(f"/api/v1/projects/{project['id']}/epics", json={"title": "E"})
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "F"},
        )
    ).json()
    task_resp = (
        await client.post(
            f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
            json={"title": "T"},
        )
    ).json()
    await client.patch(
        f"/api/v1/tasks/{task_resp['id']}",
        json={"pr_url": pr_url, "status": "review"},
    )

    # Set pr_head_sha directly (not exposed via API — set by webhook consumer in prod)
    task_row = (
        await db_session.execute(sa_select(Task).where(Task.id == task_resp["id"]))
    ).scalar_one()
    task_row.pr_head_sha = sha
    await db_session.commit()

    # Insert a passing codex turn
    db_session.add(
        PrReviewTurn(
            project_id=project["id"],
            pr_url=pr_url,
            pr_number=int(pr_url.split("/")[-1], 16),
            head_sha=sha,
            stage="codex",
            turn_number=1,
            status="completed",
            consensus_reached=True,
        )
    )
    await db_session.commit()

    board = (await client.get(f"/api/v1/projects/{project['id']}/board")).json()
    cards = [c for col in board["columns"] for c in col["tasks"] if c["id"] == task_resp["id"]]
    assert cards, "task not found on board"
    card = cards[0]

    assert card["codex_status"] == "pass"
    assert card["codex_progress"] is None
    assert card["codex_review_picked_up"] is True  # deprecated boolean still correct
