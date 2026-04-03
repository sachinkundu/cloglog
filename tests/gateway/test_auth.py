"""Tests for Gateway auth middleware."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_protected_endpoint_rejects_missing_key(client: AsyncClient) -> None:
    """Requests without an API key get 401."""
    response = await client.get("/api/v1/gateway/me")
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing API key"


@pytest.mark.asyncio
async def test_protected_endpoint_rejects_invalid_key(client: AsyncClient) -> None:
    """Requests with an invalid API key get 401."""
    response = await client.get(
        "/api/v1/gateway/me",
        headers={"X-API-Key": "invalid-key-that-does-not-exist"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid API key"


@pytest.mark.asyncio
async def test_protected_endpoint_accepts_valid_key(client: AsyncClient) -> None:
    """Requests with a valid API key get 200 and project info."""
    # Create a project to get a valid API key
    create_resp = await client.post(
        "/api/v1/projects",
        json={"name": "auth-test-project", "description": "test"},
    )
    assert create_resp.status_code == 201
    api_key = create_resp.json()["api_key"]

    # Use the key to access the protected endpoint
    response = await client.get(
        "/api/v1/gateway/me",
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "auth-test-project"
    assert "id" in data
