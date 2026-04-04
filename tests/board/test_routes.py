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
