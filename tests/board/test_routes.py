from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

# --- Project endpoints ---


async def test_create_project(client: AsyncClient):
    resp = await client.post("/api/v1/projects", json={"name": "route-test"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "route-test"
    assert "api_key" in data
    assert len(data["api_key"]) == 64


async def test_list_projects(client: AsyncClient):
    await client.post("/api/v1/projects", json={"name": "list-test-1"})
    await client.post("/api/v1/projects", json={"name": "list-test-2"})
    resp = await client.get("/api/v1/projects")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 2


async def test_get_project(client: AsyncClient):
    create_resp = await client.post("/api/v1/projects", json={"name": "get-test"})
    project_id = create_resp.json()["id"]
    resp = await client.get(f"/api/v1/projects/{project_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "get-test"


async def test_get_project_not_found(client: AsyncClient):
    resp = await client.get("/api/v1/projects/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


# --- Epic endpoints ---


async def test_create_epic(client: AsyncClient):
    project = (await client.post("/api/v1/projects", json={"name": "epic-test"})).json()
    resp = await client.post(
        f"/api/v1/projects/{project['id']}/epics",
        json={"title": "Auth Epic"},
    )
    assert resp.status_code == 201
    assert resp.json()["title"] == "Auth Epic"


async def test_list_epics(client: AsyncClient):
    project = (await client.post("/api/v1/projects", json={"name": "epic-list-test"})).json()
    await client.post(f"/api/v1/projects/{project['id']}/epics", json={"title": "E1"})
    await client.post(f"/api/v1/projects/{project['id']}/epics", json={"title": "E2"})
    resp = await client.get(f"/api/v1/projects/{project['id']}/epics")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


# --- Feature endpoints ---


async def test_create_feature(client: AsyncClient):
    project = (await client.post("/api/v1/projects", json={"name": "feat-test"})).json()
    epic = (
        await client.post(f"/api/v1/projects/{project['id']}/epics", json={"title": "Epic"})
    ).json()
    resp = await client.post(
        f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
        json={"title": "Login Feature"},
    )
    assert resp.status_code == 201
    assert resp.json()["title"] == "Login Feature"


# --- Task endpoints ---


async def test_create_task(client: AsyncClient):
    project = (await client.post("/api/v1/projects", json={"name": "task-test"})).json()
    epic = (
        await client.post(f"/api/v1/projects/{project['id']}/epics", json={"title": "Epic"})
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "Feature"},
        )
    ).json()
    resp = await client.post(
        f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
        json={"title": "Write tests"},
    )
    assert resp.status_code == 201
    assert resp.json()["title"] == "Write tests"
    assert resp.json()["status"] == "backlog"


async def test_update_task(client: AsyncClient):
    project = (await client.post("/api/v1/projects", json={"name": "task-update-test"})).json()
    epic = (
        await client.post(f"/api/v1/projects/{project['id']}/epics", json={"title": "Epic"})
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "Feature"},
        )
    ).json()
    task = (
        await client.post(
            f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
            json={"title": "Task"},
        )
    ).json()
    resp = await client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"status": "in_progress"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "in_progress"


async def test_update_task_status_emits_event(client: AsyncClient):
    """When task status changes, a TASK_STATUS_CHANGED event is published."""
    project = (await client.post("/api/v1/projects", json={"name": "event-test"})).json()
    epic = (
        await client.post(f"/api/v1/projects/{project['id']}/epics", json={"title": "Epic"})
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "Feature"},
        )
    ).json()
    task = (
        await client.post(
            f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
            json={"title": "Task"},
        )
    ).json()

    with patch("src.board.routes.event_bus.publish", new_callable=AsyncMock) as mock_publish:
        resp = await client.patch(
            f"/api/v1/tasks/{task['id']}",
            json={"status": "in_progress"},
        )
        assert resp.status_code == 200
        mock_publish.assert_called_once()
        event = mock_publish.call_args[0][0]
        assert event.type == "task_status_changed"
        assert str(event.project_id) == project["id"]
        assert event.data["task_id"] == task["id"]
        assert event.data["old_status"] == "backlog"
        assert event.data["new_status"] == "in_progress"


async def test_update_task_no_event_when_no_status_change(client: AsyncClient):
    """No event emitted when updating non-status fields."""
    project = (await client.post("/api/v1/projects", json={"name": "no-event-test"})).json()
    epic = (
        await client.post(f"/api/v1/projects/{project['id']}/epics", json={"title": "Epic"})
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "Feature"},
        )
    ).json()
    task = (
        await client.post(
            f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
            json={"title": "Task"},
        )
    ).json()

    with patch("src.board.routes.event_bus.publish", new_callable=AsyncMock) as mock_publish:
        resp = await client.patch(
            f"/api/v1/tasks/{task['id']}",
            json={"title": "Updated Title"},
        )
        assert resp.status_code == 200
        mock_publish.assert_not_called()


async def test_delete_task(client: AsyncClient):
    project = (await client.post("/api/v1/projects", json={"name": "task-del-test"})).json()
    epic = (
        await client.post(f"/api/v1/projects/{project['id']}/epics", json={"title": "Epic"})
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "Feature"},
        )
    ).json()
    task = (
        await client.post(
            f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
            json={"title": "Task"},
        )
    ).json()
    resp = await client.delete(f"/api/v1/tasks/{task['id']}")
    assert resp.status_code == 204


# --- Board endpoint ---


async def test_get_board(client: AsyncClient):
    project = (await client.post("/api/v1/projects", json={"name": "board-test"})).json()
    epic = (
        await client.post(f"/api/v1/projects/{project['id']}/epics", json={"title": "Epic"})
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "Feature"},
        )
    ).json()
    await client.post(
        f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
        json={"title": "T1"},
    )
    await client.post(
        f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
        json={"title": "T2"},
    )
    resp = await client.get(f"/api/v1/projects/{project['id']}/board")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_tasks"] == 2
    assert data["done_count"] == 0
    # Find the backlog column
    backlog = next(c for c in data["columns"] if c["status"] == "backlog")
    assert len(backlog["tasks"]) == 2


async def test_get_board_has_four_columns(client: AsyncClient):
    project = (await client.post("/api/v1/projects", json={"name": "columns-test"})).json()
    resp = await client.get(f"/api/v1/projects/{project['id']}/board")
    assert resp.status_code == 200
    data = resp.json()
    statuses = [c["status"] for c in data["columns"]]
    assert statuses == ["backlog", "in_progress", "review", "done"]


async def test_archive_task_persists(client: AsyncClient):
    project = (await client.post("/api/v1/projects", json={"name": "archive-test"})).json()
    epic = (
        await client.post(f"/api/v1/projects/{project['id']}/epics", json={"title": "Epic"})
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "Feature"},
        )
    ).json()
    task = (
        await client.post(
            f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
            json={"title": "T1"},
        )
    ).json()

    # Mark as done then archive
    await client.patch(f"/api/v1/tasks/{task['id']}", json={"status": "done"})
    resp = await client.patch(f"/api/v1/tasks/{task['id']}", json={"archived": True})
    assert resp.status_code == 200
    assert resp.json()["archived"] is True

    # Verify archived persists through board fetch
    board = (await client.get(f"/api/v1/projects/{project['id']}/board")).json()
    done_col = next(c for c in board["columns"] if c["status"] == "done")
    archived_task = next(t for t in done_col["tasks"] if t["id"] == task["id"])
    assert archived_task["archived"] is True


# --- Import endpoint ---


async def test_create_epic_auto_assigns_color(client: AsyncClient):
    project = (await client.post("/api/v1/projects", json={"name": "color-test"})).json()
    epic = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics",
            json={"title": "Epic 1"},
        )
    ).json()
    assert "color" in epic
    assert epic["color"].startswith("#")
    assert len(epic["color"]) == 7


async def test_epics_get_distinct_colors(client: AsyncClient):
    project = (await client.post("/api/v1/projects", json={"name": "multi-color"})).json()
    colors = []
    for i in range(4):
        epic = (
            await client.post(
                f"/api/v1/projects/{project['id']}/epics",
                json={"title": f"Epic {i}"},
            )
        ).json()
        colors.append(epic["color"])
    assert len(set(colors)) == 4


async def test_board_tasks_include_epic_color(client: AsyncClient):
    project = (await client.post("/api/v1/projects", json={"name": "board-color"})).json()
    epic = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics",
            json={"title": "Colored Epic"},
        )
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "Feature"},
        )
    ).json()
    await client.post(
        f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
        json={"title": "Task"},
    )

    resp = await client.get(f"/api/v1/projects/{project['id']}/board")
    assert resp.status_code == 200
    board = resp.json()
    backlog_tasks = [c for c in board["columns"] if c["status"] == "backlog"][0]["tasks"]
    assert len(backlog_tasks) >= 1
    assert "epic_color" in backlog_tasks[0]
    assert backlog_tasks[0]["epic_color"] == epic["color"]


async def test_import_plan(client: AsyncClient):
    project = (await client.post("/api/v1/projects", json={"name": "import-test"})).json()
    plan = {
        "epics": [
            {
                "title": "Backend",
                "features": [
                    {
                        "title": "Auth",
                        "tasks": [
                            {"title": "Login"},
                            {"title": "Signup"},
                        ],
                    },
                    {
                        "title": "API",
                        "tasks": [
                            {"title": "REST endpoints"},
                        ],
                    },
                ],
            }
        ]
    }
    resp = await client.post(
        f"/api/v1/projects/{project['id']}/import",
        json=plan,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["epics_created"] == 1
    assert data["features_created"] == 2
    assert data["tasks_created"] == 3


# --- Backlog endpoint ---


async def test_delete_epic(client: AsyncClient):
    project = (await client.post("/api/v1/projects", json={"name": "epic-del-test"})).json()
    epic = (
        await client.post(f"/api/v1/projects/{project['id']}/epics", json={"title": "Epic"})
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "Feature"},
        )
    ).json()
    await client.post(
        f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
        json={"title": "Task"},
    )
    resp = await client.delete(f"/api/v1/epics/{epic['id']}")
    assert resp.status_code == 204
    # Verify cascade: features and tasks are gone
    epics_resp = await client.get(f"/api/v1/projects/{project['id']}/epics")
    assert len(epics_resp.json()) == 0


async def test_delete_epic_not_found(client: AsyncClient):
    resp = await client.delete("/api/v1/epics/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


async def test_delete_feature(client: AsyncClient):
    project = (await client.post("/api/v1/projects", json={"name": "feat-del-test"})).json()
    epic = (
        await client.post(f"/api/v1/projects/{project['id']}/epics", json={"title": "Epic"})
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "Feature"},
        )
    ).json()
    await client.post(
        f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
        json={"title": "Task"},
    )
    resp = await client.delete(f"/api/v1/features/{feature['id']}")
    assert resp.status_code == 204
    # Verify cascade: tasks are gone, epic still exists
    features_resp = await client.get(
        f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features"
    )
    assert len(features_resp.json()) == 0
    epics_resp = await client.get(f"/api/v1/projects/{project['id']}/epics")
    assert len(epics_resp.json()) == 1


async def test_delete_feature_not_found(client: AsyncClient):
    resp = await client.delete("/api/v1/features/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


async def test_backlog_returns_tree(client: AsyncClient):
    project = (await client.post("/api/v1/projects", json={"name": "backlog-test"})).json()
    epic = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics",
            json={"title": "Auth"},
        )
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "OAuth"},
        )
    ).json()
    await client.post(
        f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
        json={"title": "Callback handler"},
    )
    await client.post(
        f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
        json={"title": "Token refresh"},
    )

    resp = await client.get(f"/api/v1/projects/{project['id']}/backlog")
    assert resp.status_code == 200
    data = resp.json()

    assert len(data) == 1
    assert data[0]["epic"]["title"] == "Auth"
    assert data[0]["epic"]["color"].startswith("#")
    assert data[0]["task_counts"]["total"] == 2
    assert data[0]["task_counts"]["done"] == 0

    features = data[0]["features"]
    assert len(features) == 1
    assert features[0]["feature"]["title"] == "OAuth"
    assert features[0]["task_counts"]["total"] == 2
    assert len(features[0]["tasks"]) == 2
    assert features[0]["tasks"][0]["title"] == "Callback handler"


async def test_backlog_counts_done_tasks(client: AsyncClient):
    project = (await client.post("/api/v1/projects", json={"name": "backlog-done"})).json()
    epic = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics",
            json={"title": "Epic"},
        )
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "Feature"},
        )
    ).json()
    task = (
        await client.post(
            f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
            json={"title": "Task 1"},
        )
    ).json()
    await client.post(
        f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
        json={"title": "Task 2"},
    )
    await client.patch(f"/api/v1/tasks/{task['id']}", json={"status": "done"})

    resp = await client.get(f"/api/v1/projects/{project['id']}/backlog")
    data = resp.json()
    assert data[0]["task_counts"]["total"] == 2
    assert data[0]["task_counts"]["done"] == 1
    assert data[0]["features"][0]["task_counts"]["done"] == 1


async def test_backlog_backfills_empty_epic_colors(client: AsyncClient):
    """Epics with empty color get auto-assigned on backlog fetch."""
    project = (await client.post("/api/v1/projects", json={"name": "backfill-test"})).json()
    # Create epic via import (simulating pre-color-feature creation)
    await client.post(
        f"/api/v1/projects/{project['id']}/import",
        json={
            "epics": [
                {"title": "Old Epic", "features": [{"title": "Feat", "tasks": [{"title": "Task"}]}]}
            ]
        },
    )

    # Fetch backlog — should trigger backfill
    resp = await client.get(f"/api/v1/projects/{project['id']}/backlog")
    data = resp.json()
    assert len(data) == 1
    assert data[0]["epic"]["color"].startswith("#")
    assert len(data[0]["epic"]["color"]) == 7


# --- Entity number tests ---


async def test_epic_response_includes_number(client: AsyncClient):
    project = (await client.post("/api/v1/projects", json={"name": "num-test"})).json()
    epic = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics",
            json={"title": "First Epic"},
        )
    ).json()
    assert "number" in epic
    assert epic["number"] == 1


async def test_entity_numbers_auto_increment(client: AsyncClient):
    project = (await client.post("/api/v1/projects", json={"name": "num-incr"})).json()
    e1 = (await client.post(f"/api/v1/projects/{project['id']}/epics", json={"title": "E1"})).json()
    e2 = (await client.post(f"/api/v1/projects/{project['id']}/epics", json={"title": "E2"})).json()
    assert e1["number"] == 1
    assert e2["number"] == 2

    f1 = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{e1['id']}/features",
            json={"title": "F1"},
        )
    ).json()
    f2 = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{e2['id']}/features",
            json={"title": "F2"},
        )
    ).json()
    assert f1["number"] == 1
    assert f2["number"] == 2

    t1 = (
        await client.post(
            f"/api/v1/projects/{project['id']}/features/{f1['id']}/tasks",
            json={"title": "T1"},
        )
    ).json()
    t2 = (
        await client.post(
            f"/api/v1/projects/{project['id']}/features/{f2['id']}/tasks",
            json={"title": "T2"},
        )
    ).json()
    assert t1["number"] == 1
    assert t2["number"] == 2


# --- SSE event emission tests ---


async def test_create_epic_emits_event(client: AsyncClient):
    """Creating an epic emits an EPIC_CREATED event."""
    project = (await client.post("/api/v1/projects", json={"name": "epic-event-test"})).json()

    with patch("src.board.routes.event_bus.publish", new_callable=AsyncMock) as mock_publish:
        resp = await client.post(
            f"/api/v1/projects/{project['id']}/epics",
            json={"title": "New Epic"},
        )
        assert resp.status_code == 201
        mock_publish.assert_called_once()
        event = mock_publish.call_args[0][0]
        assert event.type == "epic_created"
        assert str(event.project_id) == project["id"]
        assert event.data["title"] == "New Epic"


async def test_create_feature_emits_event(client: AsyncClient):
    """Creating a feature emits a FEATURE_CREATED event."""
    project = (await client.post("/api/v1/projects", json={"name": "feat-event-test"})).json()
    epic = (
        await client.post(f"/api/v1/projects/{project['id']}/epics", json={"title": "Epic"})
    ).json()

    with patch("src.board.routes.event_bus.publish", new_callable=AsyncMock) as mock_publish:
        resp = await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "New Feature"},
        )
        assert resp.status_code == 201
        mock_publish.assert_called_once()
        event = mock_publish.call_args[0][0]
        assert event.type == "feature_created"
        assert str(event.project_id) == project["id"]
        assert event.data["title"] == "New Feature"


async def test_create_task_emits_event(client: AsyncClient):
    """Creating a task emits a TASK_CREATED event."""
    project = (await client.post("/api/v1/projects", json={"name": "task-event-test"})).json()
    epic = (
        await client.post(f"/api/v1/projects/{project['id']}/epics", json={"title": "Epic"})
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "Feature"},
        )
    ).json()

    with patch("src.board.routes.event_bus.publish", new_callable=AsyncMock) as mock_publish:
        resp = await client.post(
            f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
            json={"title": "New Task"},
        )
        assert resp.status_code == 201
        mock_publish.assert_called_once()
        event = mock_publish.call_args[0][0]
        assert event.type == "task_created"
        assert str(event.project_id) == project["id"]
        assert event.data["title"] == "New Task"


async def test_delete_epic_emits_event(client: AsyncClient):
    """Deleting an epic emits an EPIC_DELETED event."""
    project = (await client.post("/api/v1/projects", json={"name": "del-epic-test"})).json()
    epic = (
        await client.post(f"/api/v1/projects/{project['id']}/epics", json={"title": "Epic"})
    ).json()

    with patch("src.board.routes.event_bus.publish", new_callable=AsyncMock) as mock_publish:
        resp = await client.delete(f"/api/v1/epics/{epic['id']}")
        assert resp.status_code == 204
        mock_publish.assert_called_once()
        event = mock_publish.call_args[0][0]
        assert event.type == "epic_deleted"
        assert str(event.project_id) == project["id"]
        assert event.data["epic_id"] == epic["id"]


async def test_delete_feature_emits_event(client: AsyncClient):
    """Deleting a feature emits a FEATURE_DELETED event."""
    project = (await client.post("/api/v1/projects", json={"name": "del-feat-test"})).json()
    epic = (
        await client.post(f"/api/v1/projects/{project['id']}/epics", json={"title": "Epic"})
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "Feature"},
        )
    ).json()

    with patch("src.board.routes.event_bus.publish", new_callable=AsyncMock) as mock_publish:
        resp = await client.delete(f"/api/v1/features/{feature['id']}")
        assert resp.status_code == 204
        mock_publish.assert_called_once()
        event = mock_publish.call_args[0][0]
        assert event.type == "feature_deleted"
        assert str(event.project_id) == project["id"]
        assert event.data["feature_id"] == feature["id"]


async def test_delete_task_emits_event(client: AsyncClient):
    """Deleting a task emits a TASK_DELETED event."""
    project = (await client.post("/api/v1/projects", json={"name": "del-task-test"})).json()
    epic = (
        await client.post(f"/api/v1/projects/{project['id']}/epics", json={"title": "Epic"})
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "Feature"},
        )
    ).json()
    task = (
        await client.post(
            f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
            json={"title": "Task"},
        )
    ).json()

    with patch("src.board.routes.event_bus.publish", new_callable=AsyncMock) as mock_publish:
        resp = await client.delete(f"/api/v1/tasks/{task['id']}")
        assert resp.status_code == 204
        mock_publish.assert_called_once()
        event = mock_publish.call_args[0][0]
        assert event.type == "task_deleted"
        assert str(event.project_id) == project["id"]
        assert event.data["task_id"] == task["id"]


# --- Notification endpoints ---


async def test_get_notifications_returns_unread(client: AsyncClient):
    """GET /notifications returns unread notifications (empty initially)."""
    project = (await client.post("/api/v1/projects", json={"name": "notif-test"})).json()
    resp = await client.get(f"/api/v1/projects/{project['id']}/notifications")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_mark_notification_read_404(client: AsyncClient):
    """PATCH /notifications/{id}/read returns 404 for non-existent notification."""
    resp = await client.patch("/api/v1/notifications/00000000-0000-0000-0000-000000000000/read")
    assert resp.status_code == 404


async def test_mark_all_notifications_read(client: AsyncClient):
    """POST /notifications/read-all marks all as read."""
    project = (await client.post("/api/v1/projects", json={"name": "notif-readall"})).json()
    resp = await client.post(f"/api/v1/projects/{project['id']}/notifications/read-all")
    assert resp.status_code == 200
    assert resp.json()["marked_read"] == 0


# --- Search endpoint ---


async def _create_test_hierarchy(client: AsyncClient, project_name: str) -> dict:
    """Helper to create a project with epic, feature, and task. Returns all IDs."""
    project = (await client.post("/api/v1/projects", json={"name": project_name})).json()
    epic = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics",
            json={"title": "Auth Epic"},
        )
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "Login Feature"},
        )
    ).json()
    task = (
        await client.post(
            f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
            json={"title": "Write Login Tests"},
        )
    ).json()
    return {
        "project": project,
        "epic": epic,
        "feature": feature,
        "task": task,
    }


async def test_search_by_title(client: AsyncClient):
    """Search by title substring returns matching results."""
    h = await _create_test_hierarchy(client, "search-title-test")
    pid = h["project"]["id"]
    resp = await client.get(f"/api/v1/projects/{pid}/search", params={"q": "Auth"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "Auth"
    assert data["total"] >= 1
    titles = [r["title"] for r in data["results"]]
    assert "Auth Epic" in titles


async def test_search_case_insensitive(client: AsyncClient):
    """Search is case-insensitive (ILIKE)."""
    h = await _create_test_hierarchy(client, "search-case-test")
    pid = h["project"]["id"]
    resp = await client.get(f"/api/v1/projects/{pid}/search", params={"q": "auth epic"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    titles = [r["title"] for r in data["results"]]
    assert "Auth Epic" in titles


async def test_search_by_entity_number(client: AsyncClient):
    """Search 'T-1' finds the task with number 1."""
    h = await _create_test_hierarchy(client, "search-tnum-test")
    pid = h["project"]["id"]
    resp = await client.get(f"/api/v1/projects/{pid}/search", params={"q": "T-1"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    types = [r["type"] for r in data["results"]]
    assert "task" in types
    task_result = next(r for r in data["results"] if r["type"] == "task")
    assert task_result["number"] == 1


async def test_search_by_bare_number(client: AsyncClient):
    """Search '1' matches entities with number 1 across all types."""
    h = await _create_test_hierarchy(client, "search-barenum-test")
    pid = h["project"]["id"]
    resp = await client.get(f"/api/v1/projects/{pid}/search", params={"q": "1"})
    assert resp.status_code == 200
    data = resp.json()
    # All entities have number 1, so all three should match
    assert data["total"] >= 3
    types = {r["type"] for r in data["results"]}
    assert types == {"epic", "feature", "task"}


async def test_search_type_prefix_filters(client: AsyncClient):
    """Search 'E-1' only returns epics, not features or tasks."""
    h = await _create_test_hierarchy(client, "search-prefix-test")
    pid = h["project"]["id"]
    resp = await client.get(f"/api/v1/projects/{pid}/search", params={"q": "E-1"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    types = {r["type"] for r in data["results"]}
    assert types == {"epic"}


async def test_search_respects_limit(client: AsyncClient):
    """Search with limit=1 returns at most 1 result."""
    h = await _create_test_hierarchy(client, "search-limit-test")
    pid = h["project"]["id"]
    # Search for something that matches multiple items
    resp = await client.get(f"/api/v1/projects/{pid}/search", params={"q": "1", "limit": 1})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["results"]) == 1
    # total reflects the actual count, not the limited results
    assert data["total"] >= 1


async def test_search_empty_query_rejected(client: AsyncClient):
    """Empty query string returns 422 validation error."""
    h = await _create_test_hierarchy(client, "search-empty-test")
    pid = h["project"]["id"]
    resp = await client.get(f"/api/v1/projects/{pid}/search", params={"q": ""})
    assert resp.status_code == 422


async def test_search_invalid_project_404(client: AsyncClient):
    """Search with non-existent project ID returns 404."""
    resp = await client.get(
        "/api/v1/projects/00000000-0000-0000-0000-000000000000/search",
        params={"q": "test"},
    )
    assert resp.status_code == 404


async def test_search_includes_breadcrumbs(client: AsyncClient):
    """Task search results include epic_title, epic_color, and feature_title."""
    h = await _create_test_hierarchy(client, "search-breadcrumb-test")
    pid = h["project"]["id"]
    resp = await client.get(f"/api/v1/projects/{pid}/search", params={"q": "Write Login Tests"})
    assert resp.status_code == 200
    data = resp.json()
    task_results = [r for r in data["results"] if r["type"] == "task"]
    assert len(task_results) >= 1
    task_r = task_results[0]
    assert task_r["epic_title"] == "Auth Epic"
    assert task_r["epic_color"] is not None
    assert task_r["epic_color"].startswith("#")
    assert task_r["feature_title"] == "Login Feature"


async def test_search_returns_all_entity_types(client: AsyncClient):
    """Search for a term present in all entity types returns epics, features, and tasks."""
    project = (await client.post("/api/v1/projects", json={"name": "search-alltypes-test"})).json()
    pid = project["id"]
    epic = (
        await client.post(
            f"/api/v1/projects/{pid}/epics",
            json={"title": "Shared Keyword Widget"},
        )
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{pid}/epics/{epic['id']}/features",
            json={"title": "Widget Config"},
        )
    ).json()
    await client.post(
        f"/api/v1/projects/{pid}/features/{feature['id']}/tasks",
        json={"title": "Widget Styling"},
    )

    resp = await client.get(f"/api/v1/projects/{pid}/search", params={"q": "Widget"})
    assert resp.status_code == 200
    data = resp.json()
    types = {r["type"] for r in data["results"]}
    assert types == {"epic", "feature", "task"}
    assert data["total"] == 3


async def test_search_status_filter_open(client: AsyncClient):
    """status_filter restricts results to tasks with matching statuses."""
    h = await _create_test_hierarchy(client, "search-status-open")
    pid = h["project"]["id"]
    fid = h["feature"]["id"]

    # Default task is backlog (open). Create a done task too.
    await client.post(
        f"/api/v1/projects/{pid}/features/{fid}/tasks",
        json={"title": "Write Login Tests Done"},
    )
    done_task = (await client.get(f"/api/v1/projects/{pid}/search", params={"q": "Done"})).json()[
        "results"
    ]
    done_tid = done_task[0]["id"]
    await client.patch(f"/api/v1/tasks/{done_tid}", json={"status": "done"})

    # Filter for open statuses only
    resp = await client.get(
        f"/api/v1/projects/{pid}/search",
        params={"q": "Login Tests", "status_filter": ["backlog", "in_progress", "review"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    statuses = {r["status"] for r in data["results"]}
    assert "done" not in statuses
    assert data["total"] >= 1


async def test_search_status_filter_closed(client: AsyncClient):
    """status_filter=done returns only done tasks."""
    h = await _create_test_hierarchy(client, "search-status-closed")
    pid = h["project"]["id"]
    tid = h["task"]["id"]

    # Move task to done
    await client.patch(f"/api/v1/tasks/{tid}", json={"status": "done"})

    resp = await client.get(
        f"/api/v1/projects/{pid}/search",
        params={"q": "Login Tests", "status_filter": ["done"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert all(r["status"] == "done" for r in data["results"])


async def test_search_status_filter_excludes_epics_features(client: AsyncClient):
    """When status_filter is set, only tasks are searched (not epics/features)."""
    project = (await client.post("/api/v1/projects", json={"name": "search-filter-types"})).json()
    pid = project["id"]
    epic = (
        await client.post(
            f"/api/v1/projects/{pid}/epics",
            json={"title": "Shared Keyword Widget"},
        )
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{pid}/epics/{epic['id']}/features",
            json={"title": "Widget Config"},
        )
    ).json()
    await client.post(
        f"/api/v1/projects/{pid}/features/{feature['id']}/tasks",
        json={"title": "Widget Styling"},
    )

    # Without filter — all types
    resp = await client.get(f"/api/v1/projects/{pid}/search", params={"q": "Widget"})
    assert {r["type"] for r in resp.json()["results"]} == {"epic", "feature", "task"}

    # With filter — only tasks
    resp = await client.get(
        f"/api/v1/projects/{pid}/search",
        params={"q": "Widget", "status_filter": ["backlog"]},
    )
    data = resp.json()
    assert all(r["type"] == "task" for r in data["results"])
    assert data["total"] >= 1


async def test_search_no_status_filter_returns_all(client: AsyncClient):
    """Without status_filter, search returns all entity types as before."""
    h = await _create_test_hierarchy(client, "search-no-filter")
    pid = h["project"]["id"]
    resp = await client.get(f"/api/v1/projects/{pid}/search", params={"q": "Auth"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    # Should include the epic at minimum
    types = {r["type"] for r in data["results"]}
    assert "epic" in types


# --- Reorder endpoints ---


async def test_reorder_epics(client: AsyncClient):
    """Reorder epics and verify via backlog endpoint."""
    project = (await client.post("/api/v1/projects", json={"name": "reorder-epics"})).json()
    e1 = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics", json={"title": "Epic A", "position": 0}
        )
    ).json()
    e2 = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics", json={"title": "Epic B", "position": 1}
        )
    ).json()

    # Swap order
    resp = await client.post(
        f"/api/v1/projects/{project['id']}/epics/reorder",
        json={"items": [{"id": e2["id"], "position": 0}, {"id": e1["id"], "position": 1}]},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

    # Verify via backlog
    backlog = (await client.get(f"/api/v1/projects/{project['id']}/backlog")).json()
    assert backlog[0]["epic"]["id"] == e2["id"]
    assert backlog[1]["epic"]["id"] == e1["id"]


async def test_reorder_tasks(client: AsyncClient):
    """Reorder tasks within a feature and verify via backlog."""
    project = (await client.post("/api/v1/projects", json={"name": "reorder-tasks"})).json()
    epic = (
        await client.post(f"/api/v1/projects/{project['id']}/epics", json={"title": "Epic"})
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "Feature"},
        )
    ).json()
    t1 = (
        await client.post(
            f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
            json={"title": "Task A", "position": 0},
        )
    ).json()
    t2 = (
        await client.post(
            f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
            json={"title": "Task B", "position": 1},
        )
    ).json()

    # Swap order
    resp = await client.post(
        f"/api/v1/features/{feature['id']}/tasks/reorder",
        json={"items": [{"id": t2["id"], "position": 0}, {"id": t1["id"], "position": 1}]},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

    # Verify via backlog
    backlog = (await client.get(f"/api/v1/projects/{project['id']}/backlog")).json()
    tasks = backlog[0]["features"][0]["tasks"]
    assert tasks[0]["id"] == t2["id"]
    assert tasks[1]["id"] == t1["id"]


async def test_reorder_invalid_ids(client: AsyncClient):
    """Reorder with invalid IDs returns 400."""
    project = (await client.post("/api/v1/projects", json={"name": "reorder-invalid"})).json()
    resp = await client.post(
        f"/api/v1/projects/{project['id']}/epics/reorder",
        json={
            "items": [
                {"id": "00000000-0000-0000-0000-000000000000", "position": 0},
            ]
        },
    )
    assert resp.status_code == 400


# --- Filtered board & active-tasks ---


async def _setup_board(client: AsyncClient, name: str) -> dict:
    """Create a project with two epics, each with a feature, and tasks in various statuses."""
    project = (await client.post("/api/v1/projects", json={"name": name})).json()
    pid = project["id"]
    epic1 = (await client.post(f"/api/v1/projects/{pid}/epics", json={"title": "Epic1"})).json()
    epic2 = (await client.post(f"/api/v1/projects/{pid}/epics", json={"title": "Epic2"})).json()
    feat1 = (
        await client.post(
            f"/api/v1/projects/{pid}/epics/{epic1['id']}/features",
            json={"title": "F1"},
        )
    ).json()
    feat2 = (
        await client.post(
            f"/api/v1/projects/{pid}/epics/{epic2['id']}/features",
            json={"title": "F2"},
        )
    ).json()
    # Create tasks: backlog, in_progress, done under feat1; review under feat2
    t_backlog = (
        await client.post(
            f"/api/v1/projects/{pid}/features/{feat1['id']}/tasks",
            json={"title": "T-backlog"},
        )
    ).json()
    t_progress = (
        await client.post(
            f"/api/v1/projects/{pid}/features/{feat1['id']}/tasks",
            json={"title": "T-progress"},
        )
    ).json()
    await client.patch(f"/api/v1/tasks/{t_progress['id']}", json={"status": "in_progress"})
    t_done = (
        await client.post(
            f"/api/v1/projects/{pid}/features/{feat1['id']}/tasks",
            json={"title": "T-done"},
        )
    ).json()
    await client.patch(f"/api/v1/tasks/{t_done['id']}", json={"status": "done"})
    t_review = (
        await client.post(
            f"/api/v1/projects/{pid}/features/{feat2['id']}/tasks",
            json={"title": "T-review"},
        )
    ).json()
    await client.patch(f"/api/v1/tasks/{t_review['id']}", json={"status": "review"})
    return {
        "project_id": pid,
        "epic1_id": epic1["id"],
        "epic2_id": epic2["id"],
        "feat1_id": feat1["id"],
        "feat2_id": feat2["id"],
        "t_backlog": t_backlog["id"],
        "t_progress": t_progress["id"],
        "t_done": t_done["id"],
        "t_review": t_review["id"],
    }


async def test_board_no_filters_backward_compat(client: AsyncClient):
    """get_board with no filters returns all tasks (backward compat)."""
    ids = await _setup_board(client, "board-no-filter")
    resp = await client.get(f"/api/v1/projects/{ids['project_id']}/board")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_tasks"] == 4
    assert data["done_count"] == 1


async def test_board_exclude_done(client: AsyncClient):
    """exclude_done=true omits done tasks."""
    ids = await _setup_board(client, "board-excl-done")
    resp = await client.get(
        f"/api/v1/projects/{ids['project_id']}/board", params={"exclude_done": "true"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_tasks"] == 3
    assert data["done_count"] == 0


async def test_board_filter_by_status(client: AsyncClient):
    """Filter board by specific statuses."""
    ids = await _setup_board(client, "board-status-filter")
    resp = await client.get(
        f"/api/v1/projects/{ids['project_id']}/board",
        params={"status": ["in_progress", "review"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_tasks"] == 2


async def test_board_filter_by_epic(client: AsyncClient):
    """Filter board by epic_id returns only tasks under that epic."""
    ids = await _setup_board(client, "board-epic-filter")
    resp = await client.get(
        f"/api/v1/projects/{ids['project_id']}/board",
        params={"epic_id": ids["epic2_id"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    # epic2 has only the review task
    assert data["total_tasks"] == 1


async def test_board_combined_filters(client: AsyncClient):
    """Combine epic_id and exclude_done."""
    ids = await _setup_board(client, "board-combined")
    resp = await client.get(
        f"/api/v1/projects/{ids['project_id']}/board",
        params={"epic_id": ids["epic1_id"], "exclude_done": "true"},
    )
    assert resp.status_code == 200
    data = resp.json()
    # epic1 has backlog + in_progress (done is excluded)
    assert data["total_tasks"] == 2


async def test_active_tasks_endpoint(client: AsyncClient):
    """active-tasks returns non-done, non-archived tasks with compact fields."""
    ids = await _setup_board(client, "active-tasks-test")
    resp = await client.get(f"/api/v1/projects/{ids['project_id']}/active-tasks")
    assert resp.status_code == 200
    data = resp.json()
    # 4 tasks total, 1 done → 3 active
    assert len(data) == 3
    # Verify compact fields are present
    item = data[0]
    assert "id" in item
    assert "number" in item
    assert "title" in item
    assert "status" in item
    assert "feature_id" in item
    assert "task_type" in item
    # Verify verbose fields are NOT present
    assert "description" not in item
    assert "epic_title" not in item
    assert "created_at" not in item


async def test_active_tasks_excludes_archived(client: AsyncClient):
    """active-tasks excludes archived tasks."""
    ids = await _setup_board(client, "active-archived")
    # Archive a backlog task
    await client.patch(f"/api/v1/tasks/{ids['t_backlog']}", json={"archived": True})
    resp = await client.get(f"/api/v1/projects/{ids['project_id']}/active-tasks")
    assert resp.status_code == 200
    data = resp.json()
    # 3 non-done, but 1 is archived → 2
    assert len(data) == 2


async def test_active_tasks_not_found(client: AsyncClient):
    """active-tasks returns 404 for unknown project."""
    resp = await client.get("/api/v1/projects/00000000-0000-0000-0000-000000000000/active-tasks")
    assert resp.status_code == 404


# --- Auto-Attach Document on Review ---


async def test_update_spec_task_to_review_auto_attaches_document(client: AsyncClient):
    """Spec task moved to review with pr_url auto-attaches document."""
    project = (await client.post("/api/v1/projects", json={"name": "auto-attach-route"})).json()
    epic = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics",
            json={"title": "Epic"},
        )
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "Feature"},
        )
    ).json()
    task = (
        await client.post(
            f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
            json={"title": "Write spec", "task_type": "spec"},
        )
    ).json()

    # Move to in_progress first, then to review with pr_url
    await client.patch(f"/api/v1/tasks/{task['id']}", json={"status": "in_progress"})
    resp = await client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"status": "review", "pr_url": "https://github.com/org/repo/pull/99"},
    )
    assert resp.status_code == 200

    # Check that a document was created and attached to the feature
    docs_resp = await client.get(
        "/api/v1/documents",
        params={"attached_to_type": "feature", "attached_to_id": feature["id"]},
    )
    assert docs_resp.status_code == 200
    docs = docs_resp.json()
    assert len(docs) == 1
    assert docs[0]["doc_type"] == "design_spec"
    assert docs[0]["source_path"] == "https://github.com/org/repo/pull/99"


async def test_update_impl_task_to_review_does_not_attach(client: AsyncClient):
    """Impl tasks moving to review should NOT auto-attach documents."""
    project = (await client.post("/api/v1/projects", json={"name": "no-attach-impl"})).json()
    epic = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics",
            json={"title": "Epic"},
        )
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "Feature"},
        )
    ).json()
    task = (
        await client.post(
            f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
            json={"title": "Implement", "task_type": "impl"},
        )
    ).json()

    await client.patch(f"/api/v1/tasks/{task['id']}", json={"status": "in_progress"})
    await client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"status": "review", "pr_url": "https://github.com/org/repo/pull/100"},
    )

    docs_resp = await client.get(
        "/api/v1/documents",
        params={"attached_to_type": "feature", "attached_to_id": feature["id"]},
    )
    assert docs_resp.status_code == 200
    assert len(docs_resp.json()) == 0


# --- PR Merged Field ---


async def test_task_response_includes_pr_merged(client: AsyncClient):
    """Task response includes pr_merged field, default false."""
    project = (await client.post("/api/v1/projects", json={"name": "pr-merged-test"})).json()
    epic = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics",
            json={"title": "Epic"},
        )
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "Feature"},
        )
    ).json()
    task = (
        await client.post(
            f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
            json={"title": "Task"},
        )
    ).json()

    assert "pr_merged" in task
    assert task["pr_merged"] is False


async def test_update_pr_merged(client: AsyncClient):
    """pr_merged can be set to true via PATCH."""
    project = (await client.post("/api/v1/projects", json={"name": "pr-merged-update"})).json()
    epic = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics",
            json={"title": "Epic"},
        )
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "Feature"},
        )
    ).json()
    task = (
        await client.post(
            f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
            json={
                "title": "Task",
                "task_type": "impl",
            },
        )
    ).json()

    # Set pr_url and pr_merged
    resp = await client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"pr_url": "https://github.com/org/repo/pull/50", "pr_merged": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["pr_merged"] is True
    assert data["pr_url"] == "https://github.com/org/repo/pull/50"


async def test_board_includes_pr_merged(client: AsyncClient):
    """Board endpoint returns pr_merged in task cards."""
    project = (await client.post("/api/v1/projects", json={"name": "board-pr-merged"})).json()
    epic = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics",
            json={"title": "Epic"},
        )
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "Feature"},
        )
    ).json()
    task = (
        await client.post(
            f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
            json={"title": "Task"},
        )
    ).json()

    # Mark as merged
    await client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"pr_merged": True},
    )

    resp = await client.get(f"/api/v1/projects/{project['id']}/board")
    assert resp.status_code == 200
    board = resp.json()
    backlog_tasks = board["columns"][0]["tasks"]
    assert len(backlog_tasks) == 1
    assert backlog_tasks[0]["pr_merged"] is True


async def test_active_tasks_includes_pr_merged(client: AsyncClient):
    """Active tasks endpoint includes pr_merged field."""
    project = (await client.post("/api/v1/projects", json={"name": "active-pr-merged"})).json()
    epic = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics",
            json={"title": "Epic"},
        )
    ).json()
    feature = (
        await client.post(
            f"/api/v1/projects/{project['id']}/epics/{epic['id']}/features",
            json={"title": "Feature"},
        )
    ).json()
    await client.post(
        f"/api/v1/projects/{project['id']}/features/{feature['id']}/tasks",
        json={"title": "Task"},
    )

    resp = await client.get(f"/api/v1/projects/{project['id']}/active-tasks")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert "pr_merged" in data[0]
    assert data[0]["pr_merged"] is False
