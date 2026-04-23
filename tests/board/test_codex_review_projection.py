"""T-260: Board projects a boolean ``codex_review_picked_up`` from Review.

The field flips True once any ``pr_review_turns`` row exists for the task's
``pr_url`` with ``stage='codex'``. Opencode turns do NOT flip the field.
The projection is read-only — Board never writes to ``pr_review_turns``.
"""

from __future__ import annotations

from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.review.models import PrReviewTurn


async def _make_task_with_pr(client: AsyncClient, pr_url: str) -> dict:
    project = (
        await client.post("/api/v1/projects", json={"name": f"codex-proj-{uuid4().hex[:6]}"})
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
    task = (
        await client.post(
            f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
            json={"title": "T"},
        )
    ).json()
    # Put it in the review column with a PR URL.
    await client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"pr_url": pr_url, "status": "review"},
    )
    return {"project_id": project["id"], "task_id": task["id"]}


async def _find_task_card(client: AsyncClient, project_id: str, task_id: str) -> dict:
    board = (await client.get(f"/api/v1/projects/{project_id}/board")).json()
    for col in board["columns"]:
        for card in col["tasks"]:
            if card["id"] == task_id:
                return card
    raise AssertionError(f"task {task_id} not found on board for project {project_id}")


async def test_codex_review_picked_up_starts_false(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """No pr_review_turns rows → the field is False."""
    ctx = await _make_task_with_pr(client, "https://github.com/o/r/pull/300")
    card = await _find_task_card(client, ctx["project_id"], ctx["task_id"])
    assert card["codex_review_picked_up"] is False
    assert card["pr_url"] == "https://github.com/o/r/pull/300"


async def test_codex_turn_flips_field_true(client: AsyncClient, db_session: AsyncSession) -> None:
    """Inserting a codex stage row flips the projection to True."""
    pr_url = "https://github.com/o/r/pull/301"
    ctx = await _make_task_with_pr(client, pr_url)

    # Baseline: no turn row → False.
    card_before = await _find_task_card(client, ctx["project_id"], ctx["task_id"])
    assert card_before["codex_review_picked_up"] is False

    db_session.add(
        PrReviewTurn(
            project_id=ctx["project_id"],
            pr_url=pr_url,
            pr_number=301,
            head_sha="a" * 40,
            stage="codex",
            turn_number=1,
            status="running",
        )
    )
    await db_session.commit()

    card_after = await _find_task_card(client, ctx["project_id"], ctx["task_id"])
    assert card_after["codex_review_picked_up"] is True


async def test_opencode_turn_does_not_flip_field(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """An opencode-only turn MUST NOT flip the codex field — boundary pin.

    If a future refactor makes the projection conflate stages, this test
    breaks. Keep it narrow to that regression.
    """
    pr_url = "https://github.com/o/r/pull/302"
    ctx = await _make_task_with_pr(client, pr_url)

    db_session.add(
        PrReviewTurn(
            project_id=ctx["project_id"],
            pr_url=pr_url,
            pr_number=302,
            head_sha="b" * 40,
            stage="opencode",
            turn_number=1,
            status="running",
        )
    )
    await db_session.commit()

    card = await _find_task_card(client, ctx["project_id"], ctx["task_id"])
    assert card["codex_review_picked_up"] is False


async def test_codex_turn_on_other_pr_does_not_leak(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A codex turn persisted against PR A must not flip the badge on PR B."""
    pr_a = "https://github.com/o/r/pull/400"
    pr_b = "https://github.com/o/r/pull/401"
    ctx_a = await _make_task_with_pr(client, pr_a)
    ctx_b = await _make_task_with_pr(client, pr_b)

    db_session.add(
        PrReviewTurn(
            project_id=ctx_a["project_id"],
            pr_url=pr_a,
            pr_number=400,
            head_sha="c" * 40,
            stage="codex",
            turn_number=1,
            status="running",
        )
    )
    await db_session.commit()

    card_a = await _find_task_card(client, ctx_a["project_id"], ctx_a["task_id"])
    card_b = await _find_task_card(client, ctx_b["project_id"], ctx_b["task_id"])
    assert card_a["codex_review_picked_up"] is True
    assert card_b["codex_review_picked_up"] is False


async def test_codex_turn_does_not_leak_across_projects_with_same_pr_url(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Cross-project isolation — codex MEDIUM fix from PR #198 round 1.

    Two cloglog projects can track the same GitHub PR URL today because
    the pr_url uniqueness guard is feature-scoped, not project-scoped
    (see the xfailed ``test_pr_url_reuse_blocked_cross_feature``). If
    project A persists a codex turn, project B's board MUST NOT render
    the badge on its own task that happens to share the same pr_url.
    """
    pr_url = "https://github.com/o/r/pull/500"
    ctx_a = await _make_task_with_pr(client, pr_url)
    ctx_b = await _make_task_with_pr(client, pr_url)
    # Both projects now have a task with the same pr_url. Sanity-check:
    assert ctx_a["project_id"] != ctx_b["project_id"]

    db_session.add(
        PrReviewTurn(
            project_id=ctx_a["project_id"],
            pr_url=pr_url,
            pr_number=500,
            head_sha="d" * 40,
            stage="codex",
            turn_number=1,
            status="running",
        )
    )
    await db_session.commit()

    card_a = await _find_task_card(client, ctx_a["project_id"], ctx_a["task_id"])
    card_b = await _find_task_card(client, ctx_b["project_id"], ctx_b["task_id"])
    assert card_a["codex_review_picked_up"] is True, "project A owns the turn row"
    assert card_b["codex_review_picked_up"] is False, (
        "project B must not see A's codex badge even with the same pr_url"
    )


async def test_task_without_pr_url_stays_false(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A task with no pr_url can never have ``codex_review_picked_up=True``."""
    project = (await client.post("/api/v1/projects", json={"name": "no-pr"})).json()
    epic = (
        await client.post(f"/api/v1/projects/{project['id']}/epics", json={"title": "E"})
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "F"},
        )
    ).json()
    task = (
        await client.post(
            f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
            json={"title": "T"},
        )
    ).json()

    card = await _find_task_card(client, project["id"], task["id"])
    assert card["codex_review_picked_up"] is False
    assert card["pr_url"] is None
