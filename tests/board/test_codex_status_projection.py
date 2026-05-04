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
    max_pr_sessions: int = 5,
) -> CodexStatusResult:
    for turn in turns:
        session.add(turn)
    await session.commit()

    repo = ReviewTurnRepository(session)
    result = await repo.codex_status_by_pr(
        project_id=project_id,
        pr_url_to_head_sha={pr_url: head_sha},
        max_turns=max_turns,
        max_pr_sessions=max_pr_sessions,
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


async def test_exhausted_pr_wide_session_cap_no_consensus(
    db_session: AsyncSession, project_id: UUID
) -> None:
    """T-424: EXHAUSTED iff distinct posted ``session_index`` for the PR
    reaches ``max_pr_sessions`` AND latest SHA's turns are completed
    without consensus.

    Mirrors the live state when ``MAX_REVIEWS_PER_PR=5`` posted codex
    sessions all closed without consensus on the current head_sha.
    """
    from datetime import UTC, datetime

    pr_url = "https://github.com/o/r/pull/5"
    sha = "d" * 40
    posted = datetime.now(UTC)
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
            session_index=i,
            posted_at=posted,
        )
        for i in range(1, 6)  # 5 distinct posted sessions
    ]
    result = await _status(
        db_session, project_id, pr_url, sha, turns, max_turns=1, max_pr_sessions=5
    )
    assert result.status == CodexStatus.EXHAUSTED
    assert result.progress is None


async def test_progress_when_pr_session_cap_not_yet_reached(
    db_session: AsyncSession, project_id: UUID
) -> None:
    """T-424 regression pin: a single completed non-consensus turn must NOT
    surface EXHAUSTED while the PR-wide cap (``MAX_REVIEWS_PER_PR=5``) has
    room for more review sessions.

    Pre-fix the predicate keyed off the per-session ``codex_max_turns``
    (default 1) and flipped EXHAUSTED on the first non-consensus turn even
    though four more sessions were still permitted on later pushes.
    """
    from datetime import UTC, datetime

    pr_url = "https://github.com/o/r/pull/424"
    sha = "4a" * 20
    turns = [
        PrReviewTurn(
            project_id=project_id,
            pr_url=pr_url,
            pr_number=424,
            head_sha=sha,
            stage="codex",
            turn_number=1,
            status="completed",
            consensus_reached=False,
            session_index=1,
            posted_at=datetime.now(UTC),
        ),
    ]
    result = await _status(
        db_session, project_id, pr_url, sha, turns, max_turns=1, max_pr_sessions=5
    )
    assert result.status == CodexStatus.PROGRESS
    assert result.progress is not None
    assert result.progress.turn == 1


async def test_progress_no_session_index_does_not_count_toward_exhausted(
    db_session: AsyncSession, project_id: UUID
) -> None:
    """Pre-T-375 rows (``session_index IS NULL``) are not counted toward the
    PR-wide cap — they predate the cross-session counter.

    Mirrors ``count_posted_codex_sessions`` semantics in repository.py.
    """
    pr_url = "https://github.com/o/r/pull/424null"
    sha = "5b" * 20
    turns = [
        PrReviewTurn(
            project_id=project_id,
            pr_url=pr_url,
            pr_number=4240,
            head_sha=sha,
            stage="codex",
            turn_number=i,
            status="completed",
            consensus_reached=False,
            session_index=None,
            posted_at=None,
        )
        for i in range(1, 8)  # 7 turns (distinct turn_number), none with session_index
    ]
    result = await _status(
        db_session, project_id, pr_url, sha, turns, max_turns=1, max_pr_sessions=5
    )
    assert result.status == CodexStatus.PROGRESS


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


async def test_failed_turn_then_retry_completed_shows_progress(
    db_session: AsyncSession, project_id: UUID
) -> None:
    """Turn 1 timed_out, turn 2 completed no-consensus → PROGRESS not FAILED.

    The review loop retries failed turns by inserting a higher turn_number.
    FAILED should only reflect the *latest* turn's terminal state.
    """
    pr_url = "https://github.com/o/r/pull/8b"
    sha = "ff" * 20
    turns = [
        PrReviewTurn(
            project_id=project_id,
            pr_url=pr_url,
            pr_number=8,
            head_sha=sha,
            stage="codex",
            turn_number=1,
            status="timed_out",
            consensus_reached=False,
        ),
        PrReviewTurn(
            project_id=project_id,
            pr_url=pr_url,
            pr_number=8,
            head_sha=sha,
            stage="codex",
            turn_number=2,
            status="completed",
            consensus_reached=False,
        ),
    ]
    result = await _status(db_session, project_id, pr_url, sha, turns, max_turns=3)
    assert result.status == CodexStatus.PROGRESS
    assert result.progress is not None
    assert result.progress.turn == 1


async def test_db_error_outcome_shows_failed(db_session: AsyncSession, project_id: UUID) -> None:
    """A completed turn with outcome='db_error' must project as FAILED (T-407/T-409).

    When record_findings_and_learnings raises DBAPIError, the loop stamps
    outcome='db_error' on the completed row. The board badge should surface
    this as FAILED, not PASS or PROGRESS.
    """
    pr_url = "https://github.com/o/r/pull/9db"
    sha = "ab" * 20
    turns = [
        PrReviewTurn(
            project_id=project_id,
            pr_url=pr_url,
            pr_number=9,
            head_sha=sha,
            stage="codex",
            turn_number=1,
            status="completed",
            consensus_reached=True,
            outcome="db_error",
        ),
    ]
    result = await _status(db_session, project_id, pr_url, sha, turns, max_turns=3)
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
        max_pr_sessions=5,
    )
    result_b = await repo.codex_status_by_pr(
        project_id=project_b,
        pr_url_to_head_sha={pr_url: sha},
        max_turns=1,
        max_pr_sessions=5,
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
        max_pr_sessions=5,
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


async def test_board_falls_back_to_legacy_when_two_tasks_share_pr_url(
    client: object, db_session: AsyncSession
) -> None:
    """When two tasks in one project share a pr_url, codex_status must be null
    (legacy boolean path) so the last-written sha does not shadow the other task.

    Same-project PR URL reuse is technically permitted today (project-wide guard
    is xfailed). The board must not misprojected status in that scenario.
    """
    from httpx import AsyncClient
    from sqlalchemy import select as sa_select

    from src.board.models import Task

    assert isinstance(client, AsyncClient)

    pr_url = f"https://github.com/o/r/pull/dup{uuid4().hex[:4]}"
    sha = "7a" * 20

    project = (
        await client.post("/api/v1/projects", json={"name": f"dup-{uuid4().hex[:6]}"})
    ).json()
    epic = (
        await client.post(f"/api/v1/projects/{project['id']}/epics", json={"title": "E"})
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "F"},
        )
    ).json()

    # Two tasks sharing the same PR URL within one project
    task_a = (
        await client.post(
            f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
            json={"title": "Task A"},
        )
    ).json()
    task_b = (
        await client.post(
            f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
            json={"title": "Task B"},
        )
    ).json()

    for tid in (task_a["id"], task_b["id"]):
        await client.patch(
            f"/api/v1/tasks/{tid}",
            json={"pr_url": pr_url, "status": "review"},
        )

    # Give task_a a sha and a passing codex turn
    row_a = (await db_session.execute(sa_select(Task).where(Task.id == task_a["id"]))).scalar_one()
    row_a.pr_head_sha = sha
    await db_session.commit()

    db_session.add(
        PrReviewTurn(
            project_id=project["id"],
            pr_url=pr_url,
            pr_number=int(pr_url.split("/pull/dup")[1], 16),
            head_sha=sha,
            stage="codex",
            turn_number=1,
            status="completed",
            consensus_reached=True,
        )
    )
    await db_session.commit()

    board = (await client.get(f"/api/v1/projects/{project['id']}/board")).json()
    cards = {
        c["id"]: c
        for col in board["columns"]
        for c in col["tasks"]
        if c["id"] in (task_a["id"], task_b["id"])
    }

    # Both tasks must fall back to the legacy boolean path (codex_status=null)
    # because the pr_url is shared — the discriminated path cannot safely project
    # per-task status when two tasks map to the same pr_url key.
    assert cards[task_a["id"]]["codex_status"] is None, "task_a should use legacy path"
    assert cards[task_b["id"]]["codex_status"] is None, "task_b should use legacy path"
    # codex_review_picked_up is still accurate via the legacy boolean path
    assert cards[task_a["id"]]["codex_review_picked_up"] is True


async def test_board_duplicate_pr_url_fallback_survives_exclude_done(
    client: object, db_session: AsyncSession
) -> None:
    """A done task hidden by exclude_done=true must still prevent discriminated
    projection for the live task that shares its pr_url.

    codex_status_by_pr queries pr_review_turns project-wide so historical turns
    from the done task bleed through; the duplicate guard must be project-wide too.
    """
    from httpx import AsyncClient
    from sqlalchemy import select as sa_select

    from src.board.models import Task

    assert isinstance(client, AsyncClient)

    pr_url = f"https://github.com/o/r/pull/ex{uuid4().hex[:4]}"
    sha = "8b" * 20

    project = (await client.post("/api/v1/projects", json={"name": f"ex-{uuid4().hex[:6]}"})).json()
    epic = (
        await client.post(f"/api/v1/projects/{project['id']}/epics", json={"title": "E"})
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "F"},
        )
    ).json()

    # task_done: closed task on the same pr_url (simulates a prior cycle)
    task_done = (
        await client.post(
            f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
            json={"title": "Done task"},
        )
    ).json()
    # task_live: current task that reuses the same pr_url
    task_live = (
        await client.post(
            f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
            json={"title": "Live task"},
        )
    ).json()

    for tid in (task_done["id"], task_live["id"]):
        await client.patch(
            f"/api/v1/tasks/{tid}",
            json={"pr_url": pr_url, "status": "review"},
        )
    # Move done task to done column
    await client.patch(f"/api/v1/tasks/{task_done['id']}", json={"status": "done"})

    # Give task_live a sha and a codex turn
    row_live = (
        await db_session.execute(sa_select(Task).where(Task.id == task_live["id"]))
    ).scalar_one()
    row_live.pr_head_sha = sha
    await db_session.commit()

    db_session.add(
        PrReviewTurn(
            project_id=project["id"],
            pr_url=pr_url,
            pr_number=int(pr_url.split("/pull/ex")[1], 16),
            head_sha=sha,
            stage="codex",
            turn_number=1,
            status="completed",
            consensus_reached=True,
        )
    )
    await db_session.commit()

    # Board with exclude_done=true hides task_done but the duplicate guard
    # must still scope the pr_url to legacy path for task_live.
    board = (await client.get(f"/api/v1/projects/{project['id']}/board?exclude_done=true")).json()
    live_cards = [c for col in board["columns"] for c in col["tasks"] if c["id"] == task_live["id"]]
    assert live_cards, "task_live not found on board"
    assert live_cards[0]["codex_status"] is None, (
        "shared pr_url must use legacy path even when done task is hidden"
    )
    assert live_cards[0]["codex_review_picked_up"] is True


async def test_patch_pr_url_clears_head_sha(client: object, db_session: AsyncSession) -> None:
    """Changing a task's pr_url via PATCH must clear pr_head_sha so the board
    does not project codex status against the old PR's SHA (T-409).
    """
    from httpx import AsyncClient
    from sqlalchemy import select as sa_select

    from src.board.models import Task

    assert isinstance(client, AsyncClient)

    pr_a = f"https://github.com/o/r/pull/a{uuid4().hex[:4]}"
    pr_b = f"https://github.com/o/r/pull/b{uuid4().hex[:4]}"
    sha_a = "9c" * 20

    project = (
        await client.post("/api/v1/projects", json={"name": f"sha-{uuid4().hex[:6]}"})
    ).json()
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

    # Link to pr_a and set its sha
    await client.patch(
        f"/api/v1/tasks/{task_resp['id']}",
        json={"pr_url": pr_a, "status": "review"},
    )
    row = (await db_session.execute(sa_select(Task).where(Task.id == task_resp["id"]))).scalar_one()
    row.pr_head_sha = sha_a
    await db_session.commit()

    # Relink to pr_b — sha should be cleared
    await client.patch(
        f"/api/v1/tasks/{task_resp['id']}",
        json={"pr_url": pr_b},
    )

    await db_session.refresh(row)
    assert row.pr_head_sha is None, "pr_head_sha must be cleared when pr_url changes"

    # Board must return codex_status=null (no sha → legacy path)
    board = (await client.get(f"/api/v1/projects/{project['id']}/board")).json()
    cards = [c for col in board["columns"] for c in col["tasks"] if c["id"] == task_resp["id"]]
    assert cards, "task not found on board"
    assert cards[0]["codex_status"] is None
