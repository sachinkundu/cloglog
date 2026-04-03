"""E2E tests for API key authentication.

Covers: valid key access, missing key, invalid key, and
key isolation between projects.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


def _unique_name(prefix: str = "auth-e2e") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


async def test_gateway_me_with_valid_key(client: AsyncClient) -> None:
    name = _unique_name()
    created = (
        await client.post("/api/v1/projects", json={"name": name, "description": "auth test"})
    ).json()
    api_key = created["api_key"]

    resp = await client.get("/api/v1/gateway/me", headers={"X-API-Key": api_key})
    assert resp.status_code == 200
    assert resp.json()["name"] == name
    assert resp.json()["id"] == created["id"]


async def test_gateway_me_missing_key(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/gateway/me")
    assert resp.status_code == 401


async def test_gateway_me_invalid_key(client: AsyncClient) -> None:
    resp = await client.get(
        "/api/v1/gateway/me",
        headers={"X-API-Key": "invalid-key-that-does-not-exist"},
    )
    assert resp.status_code == 401


async def test_api_key_isolation(client: AsyncClient) -> None:
    """Each project's API key should only authenticate that project."""
    name_a = _unique_name("proj-a")
    name_b = _unique_name("proj-b")

    proj_a = (await client.post("/api/v1/projects", json={"name": name_a})).json()
    proj_b = (await client.post("/api/v1/projects", json={"name": name_b})).json()

    # Key A returns project A
    resp_a = await client.get("/api/v1/gateway/me", headers={"X-API-Key": proj_a["api_key"]})
    assert resp_a.json()["name"] == name_a

    # Key B returns project B
    resp_b = await client.get("/api/v1/gateway/me", headers={"X-API-Key": proj_b["api_key"]})
    assert resp_b.json()["name"] == name_b


async def test_health_endpoint_no_auth_required(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
