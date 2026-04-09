"""E2E tests for board state consistency.

Scenario 7: Board state is always correct.
Covers hierarchy display, status roll-up, task counts,
sequential numbering, bulk import, and board filters.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.e2e.helpers import create_project_with_tasks, unique_name

pytestmark = pytest.mark.asyncio


async def _create_project(client: AsyncClient) -> dict:
    return (
        await client.post(
            "/api/v1/projects",
            json={"name": unique_name(), "description": "board consistency test"},
        )
    ).json()


async def test_epic_feature_task_hierarchy(client: AsyncClient) -> None:
    """Epic > feature > 3 tasks all appear on the board with correct breadcrumbs."""
    project = await _create_project(client)
    pid = project["id"]

    epic = (
        await client.post(
            f"/api/v1/projects/{pid}/epics",
            json={"title": "Hierarchy Epic"},
        )
    ).json()

    feature = (
        await client.post(
            f"/api/v1/projects/{pid}/epics/{epic['id']}/features",
            json={"title": "Hierarchy Feature"},
        )
    ).json()

    for i in range(3):
        await client.post(
            f"/api/v1/projects/{pid}/features/{feature['id']}/tasks",
            json={"title": f"Hierarchy Task {i + 1}"},
        )

    board = (await client.get(f"/api/v1/projects/{pid}/board")).json()
    assert board["total_tasks"] == 3

    # All tasks should be in backlog
    backlog_col = next(c for c in board["columns"] if c["status"] == "backlog")
    assert len(backlog_col["tasks"]) == 3

    # Verify breadcrumbs
    for card in backlog_col["tasks"]:
        assert card["epic_title"] == "Hierarchy Epic"
        assert card["feature_title"] == "Hierarchy Feature"


async def test_feature_status_rollup(client: AsyncClient) -> None:
    """When all tasks are done, feature status rolls up to done."""
    project = await _create_project(client)
    pid = project["id"]

    epic = (
        await client.post(f"/api/v1/projects/{pid}/epics", json={"title": "Rollup Epic"})
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{pid}/epics/{epic['id']}/features",
            json={"title": "Rollup Feature"},
        )
    ).json()

    task_ids = []
    for i in range(2):
        t = (
            await client.post(
                f"/api/v1/projects/{pid}/features/{feature['id']}/tasks",
                json={"title": f"Rollup Task {i + 1}"},
            )
        ).json()
        task_ids.append(t["id"])

    # Move both tasks to done via dashboard PATCH
    for tid in task_ids:
        resp = await client.patch(f"/api/v1/tasks/{tid}", json={"status": "done"})
        assert resp.status_code == 200

    # Check feature status via list features
    features = (await client.get(f"/api/v1/projects/{pid}/epics/{epic['id']}/features")).json()
    feat = next(f for f in features if f["id"] == feature["id"])
    assert feat["status"] == "done"


async def test_epic_status_rollup(client: AsyncClient) -> None:
    """When all features are done, epic status rolls up to done."""
    project = await _create_project(client)
    pid = project["id"]

    epic = (
        await client.post(f"/api/v1/projects/{pid}/epics", json={"title": "Epic Rollup"})
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{pid}/epics/{epic['id']}/features",
            json={"title": "Feature Rollup"},
        )
    ).json()

    task = (
        await client.post(
            f"/api/v1/projects/{pid}/features/{feature['id']}/tasks",
            json={"title": "The Only Task"},
        )
    ).json()

    # Move task to done
    await client.patch(f"/api/v1/tasks/{task['id']}", json={"status": "done"})

    # Check epic status
    epics = (await client.get(f"/api/v1/projects/{pid}/epics")).json()
    ep = next(e for e in epics if e["id"] == epic["id"])
    assert ep["status"] == "done"


async def test_partial_rollup_in_progress(client: AsyncClient) -> None:
    """One task in_progress makes the feature status in_progress."""
    project = await _create_project(client)
    pid = project["id"]

    epic = (
        await client.post(f"/api/v1/projects/{pid}/epics", json={"title": "Partial Epic"})
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{pid}/epics/{epic['id']}/features",
            json={"title": "Partial Feature"},
        )
    ).json()

    t1 = (
        await client.post(
            f"/api/v1/projects/{pid}/features/{feature['id']}/tasks",
            json={"title": "Task A"},
        )
    ).json()
    await client.post(
        f"/api/v1/projects/{pid}/features/{feature['id']}/tasks",
        json={"title": "Task B"},
    )

    # Move one to in_progress
    await client.patch(f"/api/v1/tasks/{t1['id']}", json={"status": "in_progress"})

    features = (await client.get(f"/api/v1/projects/{pid}/epics/{epic['id']}/features")).json()
    feat = next(f for f in features if f["id"] == feature["id"])
    assert feat["status"] == "in_progress"


async def test_partial_rollup_review(client: AsyncClient) -> None:
    """One task in review makes the feature status review."""
    project = await _create_project(client)
    pid = project["id"]

    epic = (
        await client.post(f"/api/v1/projects/{pid}/epics", json={"title": "Review Epic"})
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{pid}/epics/{epic['id']}/features",
            json={"title": "Review Feature"},
        )
    ).json()

    t1 = (
        await client.post(
            f"/api/v1/projects/{pid}/features/{feature['id']}/tasks",
            json={"title": "Task A"},
        )
    ).json()
    await client.post(
        f"/api/v1/projects/{pid}/features/{feature['id']}/tasks",
        json={"title": "Task B"},
    )

    # Move one to review via dashboard PATCH (status field)
    await client.patch(
        f"/api/v1/tasks/{t1['id']}",
        json={
            "status": "review",
            "pr_url": f"https://github.com/test/repo/pull/{uuid.uuid4().hex[:8]}",
        },
    )

    features = (await client.get(f"/api/v1/projects/{pid}/epics/{epic['id']}/features")).json()
    feat = next(f for f in features if f["id"] == feature["id"])
    assert feat["status"] == "review"


async def test_delete_task_updates_counts(client: AsyncClient) -> None:
    """Deleting a task reduces the board's total_tasks count."""
    pf = await create_project_with_tasks(client, n_tasks=3)

    board = (await client.get(f"/api/v1/projects/{pf.id}/board")).json()
    assert board["total_tasks"] == 3

    # Delete one task
    resp = await client.delete(f"/api/v1/tasks/{pf.task_ids[0]}")
    assert resp.status_code == 204

    board = (await client.get(f"/api/v1/projects/{pf.id}/board")).json()
    assert board["total_tasks"] == 2


async def test_entity_numbering_sequential(client: AsyncClient) -> None:
    """Tasks are numbered sequentially (T-1 through T-5)."""
    project = await _create_project(client)
    pid = project["id"]

    epic = (
        await client.post(f"/api/v1/projects/{pid}/epics", json={"title": "Numbering Epic"})
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{pid}/epics/{epic['id']}/features",
            json={"title": "Numbering Feature"},
        )
    ).json()

    numbers = []
    for i in range(5):
        t = (
            await client.post(
                f"/api/v1/projects/{pid}/features/{feature['id']}/tasks",
                json={"title": f"Seq Task {i + 1}"},
            )
        ).json()
        numbers.append(t["number"])

    # Numbers should be sequential (1, 2, 3, 4, 5)
    assert numbers == list(range(1, 6)), f"Expected sequential [1..5], got {numbers}"


async def test_bulk_import_creates_hierarchy(client: AsyncClient) -> None:
    """Bulk import creates the full epic > feature > task hierarchy."""
    project = await _create_project(client)
    pid = project["id"]

    import_plan = {
        "epics": [
            {
                "title": "Imported Epic A",
                "bounded_context": "board",
                "features": [
                    {
                        "title": "Imported Feature A1",
                        "tasks": [
                            {"title": "Imported Task 1"},
                            {"title": "Imported Task 2"},
                            {"title": "Imported Task 3"},
                        ],
                    },
                    {
                        "title": "Imported Feature A2",
                        "tasks": [
                            {"title": "Imported Task 4"},
                        ],
                    },
                ],
            }
        ]
    }

    resp = await client.post(f"/api/v1/projects/{pid}/import", json=import_plan)
    assert resp.status_code == 201
    result = resp.json()
    assert result["epics_created"] == 1
    assert result["features_created"] == 2
    assert result["tasks_created"] == 4

    # Board shows correct total
    board = (await client.get(f"/api/v1/projects/{pid}/board")).json()
    assert board["total_tasks"] == 4


async def test_board_exclude_done_filter(client: AsyncClient) -> None:
    """Board with exclude_done=true omits done tasks from total_tasks."""
    pf = await create_project_with_tasks(client, n_tasks=2)

    # Move one task to done
    await client.patch(f"/api/v1/tasks/{pf.task_ids[0]}", json={"status": "done"})

    # Without filter — all tasks
    board_all = (await client.get(f"/api/v1/projects/{pf.id}/board")).json()
    assert board_all["total_tasks"] == 2

    # With exclude_done — only non-done tasks
    board_filtered = (await client.get(f"/api/v1/projects/{pf.id}/board?exclude_done=true")).json()
    assert board_filtered["total_tasks"] == 1


async def test_board_epic_filter(client: AsyncClient) -> None:
    """Board with epic_id filter returns only that epic's tasks."""
    project = await _create_project(client)
    pid = project["id"]

    # Create two epics with tasks
    epic1 = (await client.post(f"/api/v1/projects/{pid}/epics", json={"title": "Epic One"})).json()
    feat1 = (
        await client.post(
            f"/api/v1/projects/{pid}/epics/{epic1['id']}/features",
            json={"title": "Feature One"},
        )
    ).json()
    await client.post(
        f"/api/v1/projects/{pid}/features/{feat1['id']}/tasks",
        json={"title": "Task from Epic 1"},
    )

    epic2 = (await client.post(f"/api/v1/projects/{pid}/epics", json={"title": "Epic Two"})).json()
    feat2 = (
        await client.post(
            f"/api/v1/projects/{pid}/epics/{epic2['id']}/features",
            json={"title": "Feature Two"},
        )
    ).json()
    await client.post(
        f"/api/v1/projects/{pid}/features/{feat2['id']}/tasks",
        json={"title": "Task from Epic 2"},
    )

    # Full board has both
    board_all = (await client.get(f"/api/v1/projects/{pid}/board")).json()
    assert board_all["total_tasks"] == 2

    # Filter by epic1
    board_e1 = (await client.get(f"/api/v1/projects/{pid}/board?epic_id={epic1['id']}")).json()
    assert board_e1["total_tasks"] == 1
    backlog = next(c for c in board_e1["columns"] if c["status"] == "backlog")
    assert backlog["tasks"][0]["epic_title"] == "Epic One"
