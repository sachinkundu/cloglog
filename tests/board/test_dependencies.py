"""Integration tests for feature dependency endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.fixture
async def project_with_features(client: AsyncClient) -> dict:
    """Create a project with one epic and three features for dependency tests."""
    project = (
        await client.post("/api/v1/projects", json={"name": f"dep-test-{id(object())}"})
    ).json()
    pid = project["id"]
    epic = (await client.post(f"/api/v1/projects/{pid}/epics", json={"title": "Dep Epic"})).json()
    eid = epic["id"]

    features = []
    for title in ["Feature A", "Feature B", "Feature C"]:
        f = (
            await client.post(
                f"/api/v1/projects/{pid}/epics/{eid}/features",
                json={"title": title},
            )
        ).json()
        features.append(f)

    return {"project_id": pid, "epic_id": eid, "features": features}


async def test_add_dependency(client: AsyncClient, project_with_features: dict):
    features = project_with_features["features"]
    resp = await client.post(
        f"/api/v1/features/{features[0]['id']}/dependencies",
        json={"depends_on_id": features[1]["id"]},
    )
    assert resp.status_code == 201


async def test_self_dependency_rejected(client: AsyncClient, project_with_features: dict):
    features = project_with_features["features"]
    resp = await client.post(
        f"/api/v1/features/{features[0]['id']}/dependencies",
        json={"depends_on_id": features[0]["id"]},
    )
    assert resp.status_code == 400


async def test_cycle_detection(client: AsyncClient, project_with_features: dict):
    features = project_with_features["features"]
    # A depends on B
    resp1 = await client.post(
        f"/api/v1/features/{features[0]['id']}/dependencies",
        json={"depends_on_id": features[1]["id"]},
    )
    assert resp1.status_code == 201
    # B depends on A -> cycle
    resp2 = await client.post(
        f"/api/v1/features/{features[1]['id']}/dependencies",
        json={"depends_on_id": features[0]["id"]},
    )
    assert resp2.status_code == 400
    assert "cycle" in resp2.json()["detail"].lower()


async def test_transitive_cycle_detection(client: AsyncClient, project_with_features: dict):
    features = project_with_features["features"]
    # A depends on B
    resp1 = await client.post(
        f"/api/v1/features/{features[0]['id']}/dependencies",
        json={"depends_on_id": features[1]["id"]},
    )
    assert resp1.status_code == 201
    # B depends on C
    resp2 = await client.post(
        f"/api/v1/features/{features[1]['id']}/dependencies",
        json={"depends_on_id": features[2]["id"]},
    )
    assert resp2.status_code == 201
    # C depends on A -> transitive cycle
    resp3 = await client.post(
        f"/api/v1/features/{features[2]['id']}/dependencies",
        json={"depends_on_id": features[0]["id"]},
    )
    assert resp3.status_code == 400
    assert "cycle" in resp3.json()["detail"].lower()


async def test_duplicate_dependency_rejected(client: AsyncClient, project_with_features: dict):
    features = project_with_features["features"]
    resp1 = await client.post(
        f"/api/v1/features/{features[0]['id']}/dependencies",
        json={"depends_on_id": features[1]["id"]},
    )
    assert resp1.status_code == 201
    resp2 = await client.post(
        f"/api/v1/features/{features[0]['id']}/dependencies",
        json={"depends_on_id": features[1]["id"]},
    )
    assert resp2.status_code == 409


async def test_remove_dependency(client: AsyncClient, project_with_features: dict):
    features = project_with_features["features"]
    await client.post(
        f"/api/v1/features/{features[0]['id']}/dependencies",
        json={"depends_on_id": features[1]["id"]},
    )
    resp = await client.delete(
        f"/api/v1/features/{features[0]['id']}/dependencies/{features[1]['id']}"
    )
    assert resp.status_code == 204


async def test_dependency_graph_endpoint(client: AsyncClient, project_with_features: dict):
    features = project_with_features["features"]
    pid = project_with_features["project_id"]
    # Add one dependency: A depends on B
    await client.post(
        f"/api/v1/features/{features[0]['id']}/dependencies",
        json={"depends_on_id": features[1]["id"]},
    )
    resp = await client.get(f"/api/v1/projects/{pid}/dependency-graph")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["nodes"]) == 3
    assert len(data["edges"]) == 1
    edge = data["edges"][0]
    # Edge direction: from_id is the dependency (B), to_id is the dependent (A)
    assert edge["from_id"] == features[1]["id"]
    assert edge["to_id"] == features[0]["id"]


async def test_garbage_mcp_bearer_rejected_on_add(client: AsyncClient, project_with_features: dict):
    """Regression for the pre-CurrentMcpOrDashboard auth gap: a request that
    strips the dashboard key and sends Authorization: Bearer garbage +
    X-MCP-Request: true must be rejected at the route, not passed through
    the middleware because "X-MCP-Request header is present.\"
    """
    features = project_with_features["features"]
    resp = await client.post(
        f"/api/v1/features/{features[0]['id']}/dependencies",
        json={"depends_on_id": features[1]["id"]},
        headers={
            "Authorization": "Bearer garbage",
            "X-MCP-Request": "true",
            "X-Dashboard-Key": "",
        },
    )
    assert resp.status_code == 401


async def test_garbage_mcp_bearer_rejected_on_delete(
    client: AsyncClient, project_with_features: dict
):
    features = project_with_features["features"]
    # First add the dep with the default (dashboard-key) client
    await client.post(
        f"/api/v1/features/{features[0]['id']}/dependencies",
        json={"depends_on_id": features[1]["id"]},
    )
    resp = await client.delete(
        f"/api/v1/features/{features[0]['id']}/dependencies/{features[1]['id']}",
        headers={
            "Authorization": "Bearer garbage",
            "X-MCP-Request": "true",
            "X-Dashboard-Key": "",
        },
    )
    assert resp.status_code == 401


async def test_diamond_no_cycle(client: AsyncClient, project_with_features: dict):
    """A diamond shape (A->B, A->C, B->C) is NOT a cycle and should succeed."""
    features = project_with_features["features"]
    # A depends on B
    resp1 = await client.post(
        f"/api/v1/features/{features[0]['id']}/dependencies",
        json={"depends_on_id": features[1]["id"]},
    )
    assert resp1.status_code == 201
    # A depends on C
    resp2 = await client.post(
        f"/api/v1/features/{features[0]['id']}/dependencies",
        json={"depends_on_id": features[2]["id"]},
    )
    assert resp2.status_code == 201
    # B depends on C (completing the diamond)
    resp3 = await client.post(
        f"/api/v1/features/{features[1]['id']}/dependencies",
        json={"depends_on_id": features[2]["id"]},
    )
    assert resp3.status_code == 201
