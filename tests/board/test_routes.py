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
