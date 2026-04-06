"""Tests for agent route isolation middleware.

Agents (requests with Authorization header) can only access /api/v1/agents/* routes.
All other routes return 403 for agent callers. Frontend UI (no auth) passes through.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_agent_blocked_from_board_routes(client: AsyncClient) -> None:
    """Agent requests to board routes should be rejected with 403."""
    headers = {"Authorization": "Bearer fake-api-key"}

    resp = await client.get("/api/v1/projects", headers=headers)
    assert resp.status_code == 403
    assert "Agents can only access" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_agent_blocked_from_task_patch(client: AsyncClient) -> None:
    """Agent cannot PATCH tasks via the board route."""
    headers = {"Authorization": "Bearer fake-api-key"}

    resp = await client.patch(
        "/api/v1/tasks/00000000-0000-0000-0000-000000000000",
        headers=headers,
        json={"status": "done"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_agent_allowed_on_agent_routes(client: AsyncClient) -> None:
    """Agent requests to /agents/* routes should pass through (may 401/404, but not 403)."""
    headers = {"Authorization": "Bearer fake-api-key"}

    resp = await client.post(
        "/api/v1/agents/register",
        headers=headers,
        json={"worktree_path": "/tmp/test"},
    )
    # 401 (invalid key) is expected — but NOT 403 (route blocked)
    assert resp.status_code != 403


@pytest.mark.asyncio
async def test_frontend_allowed_on_all_routes(client: AsyncClient) -> None:
    """Requests without Authorization header pass through to all routes."""
    # No auth header — this is the frontend UI
    resp = await client.get("/api/v1/projects")
    # Should not be 403 — may be 200, 404, etc. depending on data
    assert resp.status_code != 403


@pytest.mark.asyncio
async def test_agent_blocked_from_documents(client: AsyncClient) -> None:
    """Agent cannot access document routes."""
    headers = {"Authorization": "Bearer fake-api-key"}

    resp = await client.post(
        "/api/v1/documents",
        headers=headers,
        json={"title": "test"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_mcp_server_allowed_on_all_routes(client: AsyncClient) -> None:
    """Requests with X-MCP-Request header pass through even with API key."""
    headers = {
        "Authorization": "Bearer fake-api-key",
        "X-MCP-Request": "true",
    }

    resp = await client.get("/api/v1/projects", headers=headers)
    # Should not be 403 — MCP server is allowed
    assert resp.status_code != 403


@pytest.mark.asyncio
async def test_health_endpoint_not_blocked(client: AsyncClient) -> None:
    """Health check is not under /api/v1/ so it should never be blocked."""
    headers = {"Authorization": "Bearer fake-api-key"}

    resp = await client.get("/health", headers=headers)
    assert resp.status_code == 200
