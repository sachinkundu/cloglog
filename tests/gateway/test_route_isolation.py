"""Tests for API access control middleware.

Three valid access paths:
1. Agent API key (Authorization: Bearer <key>) — only /agents/* routes
2. MCP server (Authorization + X-MCP-Request) — allowed everywhere
3. Dashboard key (X-Dashboard-Key) — allowed on non-agent routes

Unauthenticated requests are rejected.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_agent_blocked_from_board_routes(client: AsyncClient) -> None:
    """Agent requests to board routes should be rejected with 403."""
    headers = {"Authorization": "Bearer fake-api-key", "X-Dashboard-Key": ""}

    resp = await client.get("/api/v1/projects", headers=headers)
    assert resp.status_code == 403
    assert "Agents can only access" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_agent_blocked_from_task_patch(client: AsyncClient) -> None:
    """Agent cannot PATCH tasks via the board route."""
    headers = {"Authorization": "Bearer fake-api-key", "X-Dashboard-Key": ""}

    resp = await client.patch(
        "/api/v1/tasks/00000000-0000-0000-0000-000000000000",
        headers=headers,
        json={"status": "done"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_agent_allowed_on_agent_routes(client: AsyncClient) -> None:
    """Agent requests to /agents/* routes should pass through (may 401/404, but not 403)."""
    headers = {"Authorization": "Bearer fake-api-key", "X-Dashboard-Key": ""}

    resp = await client.post(
        "/api/v1/agents/register",
        headers=headers,
        json={"worktree_path": "/tmp/test"},
    )
    # 401 (invalid key) is expected — but NOT 403 (route blocked)
    assert resp.status_code != 403


@pytest.mark.asyncio
async def test_dashboard_key_allowed_on_board_routes(client: AsyncClient) -> None:
    """Requests with valid X-Dashboard-Key pass through to board routes."""
    # client fixture already has the dashboard key header
    resp = await client.get("/api/v1/projects")
    assert resp.status_code != 401
    assert resp.status_code != 403


@pytest.mark.asyncio
async def test_invalid_dashboard_key_rejected(client: AsyncClient) -> None:
    """Requests with wrong X-Dashboard-Key are rejected."""
    resp = await client.get(
        "/api/v1/projects",
        headers={"X-Dashboard-Key": "wrong-key"},
    )
    assert resp.status_code == 403
    assert "Invalid dashboard key" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_unauthenticated_request_rejected(client: AsyncClient) -> None:
    """Requests with no credentials at all are rejected with 401."""
    resp = await client.get(
        "/api/v1/projects",
        headers={"X-Dashboard-Key": ""},
    )
    assert resp.status_code == 401
    assert "Authentication required" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_agent_blocked_from_documents(client: AsyncClient) -> None:
    """Agent cannot access document routes."""
    headers = {"Authorization": "Bearer fake-api-key", "X-Dashboard-Key": ""}

    resp = await client.post(
        "/api/v1/documents",
        headers=headers,
        json={"title": "test"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_mcp_server_allowed_on_all_routes(client: AsyncClient) -> None:
    """Requests with X-MCP-Request header pass through middleware."""
    headers = {
        "Authorization": "Bearer any-key",
        "X-MCP-Request": "true",
        "X-Dashboard-Key": "",
    }

    resp = await client.get("/api/v1/projects", headers=headers)
    # Should not be 403 — MCP requests pass middleware
    assert resp.status_code != 403


@pytest.mark.asyncio
async def test_health_endpoint_not_blocked(client: AsyncClient) -> None:
    """Health check is not under /api/v1/ so it should never be blocked."""
    # No credentials needed for non-API routes
    resp = await client.get("/health", headers={"X-Dashboard-Key": ""})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_dashboard_key_via_query_param(client: AsyncClient) -> None:
    """SSE/EventSource can pass dashboard key via query parameter."""
    resp = await client.get(
        "/api/v1/projects?dashboard_key=cloglog-dashboard-dev",
        headers={"X-Dashboard-Key": ""},
    )
    assert resp.status_code != 401
    assert resp.status_code != 403
