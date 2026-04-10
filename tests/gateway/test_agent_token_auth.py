"""Tests for per-agent token authentication (F-28).

Covers:
- Agent token returned on registration
- Agent token validates on agent routes
- Invalid/wrong tokens rejected
- Token rotation on re-registration
- MCP service key validation
- Header spoofing prevention
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _create_project(client: AsyncClient) -> tuple[str, str]:
    """Create a project and return (project_id, api_key)."""
    import uuid

    resp = await client.post(
        "/api/v1/projects",
        json={"name": f"auth-test-{uuid.uuid4().hex[:8]}", "description": "test"},
    )
    assert resp.status_code == 201
    data = resp.json()
    return data["id"], data["api_key"]


async def _register_agent(
    client: AsyncClient, api_key: str, worktree_path: str = "/tmp/test-wt"
) -> dict:
    """Register an agent using the project API key and return response."""
    resp = await client.post(
        "/api/v1/agents/register",
        headers={
            "Authorization": f"Bearer {api_key}",
            "X-Dashboard-Key": "",
        },
        json={"worktree_path": worktree_path},
    )
    assert resp.status_code == 201, f"Registration failed: {resp.text}"
    return resp.json()


@pytest.mark.asyncio
async def test_register_returns_agent_token(client: AsyncClient) -> None:
    """Registration response includes an agent_token field."""
    _project_id, api_key = await _create_project(client)
    result = await _register_agent(client, api_key, "/tmp/token-test-1")
    assert "agent_token" in result
    assert len(result["agent_token"]) == 32  # uuid4().hex is 32 chars
    assert result["agent_token"] != ""


@pytest.mark.asyncio
async def test_heartbeat_with_valid_agent_token(client: AsyncClient) -> None:
    """Heartbeat succeeds with a valid agent token."""
    _project_id, api_key = await _create_project(client)
    reg = await _register_agent(client, api_key, "/tmp/token-test-2")
    wt_id = reg["worktree_id"]
    token = reg["agent_token"]

    resp = await client.post(
        f"/api/v1/agents/{wt_id}/heartbeat",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Dashboard-Key": "",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_heartbeat_with_invalid_token_rejected(client: AsyncClient) -> None:
    """Heartbeat with a wrong token returns 401."""
    _project_id, api_key = await _create_project(client)
    reg = await _register_agent(client, api_key, "/tmp/token-test-3")
    wt_id = reg["worktree_id"]

    resp = await client.post(
        f"/api/v1/agents/{wt_id}/heartbeat",
        headers={
            "Authorization": "Bearer not-a-valid-token",
            "X-Dashboard-Key": "",
        },
    )
    assert resp.status_code == 401
    assert "Invalid agent token" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_heartbeat_with_wrong_worktree_id_rejected(client: AsyncClient) -> None:
    """Using agent A's token to call agent B's heartbeat returns 403."""
    _project_id, api_key = await _create_project(client)
    reg_a = await _register_agent(client, api_key, "/tmp/token-test-4a")
    reg_b = await _register_agent(client, api_key, "/tmp/token-test-4b")

    # Use agent A's token on agent B's worktree_id
    resp = await client.post(
        f"/api/v1/agents/{reg_b['worktree_id']}/heartbeat",
        headers={
            "Authorization": f"Bearer {reg_a['agent_token']}",
            "X-Dashboard-Key": "",
        },
    )
    assert resp.status_code == 403
    assert "does not match" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_agent_token_rotated_on_reregistration(client: AsyncClient) -> None:
    """Re-registering rotates the token — MCP servers are ephemeral processes."""
    _project_id, api_key = await _create_project(client)
    reg1 = await _register_agent(client, api_key, "/tmp/token-test-5")
    original_token = reg1["agent_token"]
    wt_id = reg1["worktree_id"]

    # Re-register same path — token rotates
    reg2 = await _register_agent(client, api_key, "/tmp/token-test-5")
    new_token = reg2["agent_token"]
    assert new_token is not None
    assert new_token != original_token
    assert reg2["worktree_id"] == wt_id

    # New token works
    resp = await client.post(
        f"/api/v1/agents/{wt_id}/heartbeat",
        headers={"Authorization": f"Bearer {new_token}", "X-Dashboard-Key": ""},
    )
    assert resp.status_code == 200

    # Old token is invalidated
    resp = await client.post(
        f"/api/v1/agents/{wt_id}/heartbeat",
        headers={"Authorization": f"Bearer {original_token}", "X-Dashboard-Key": ""},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_mcp_service_key_passes_middleware(client: AsyncClient) -> None:
    """Request with valid MCP service key + X-MCP-Request passes through."""
    resp = await client.get(
        "/api/v1/projects",
        headers={
            "Authorization": "Bearer cloglog-mcp-dev",
            "X-MCP-Request": "true",
            "X-Dashboard-Key": "",
        },
    )
    # Should pass middleware (200 for projects list)
    assert resp.status_code != 401
    assert resp.status_code != 403


@pytest.mark.asyncio
async def test_mcp_service_key_dependency_rejects_invalid(client: AsyncClient) -> None:
    """CurrentMcpService dependency rejects wrong MCP service key.

    The middleware passes X-MCP-Request through, but routes using
    CurrentMcpService validate the actual service key.
    """
    from starlette.requests import Request
    from starlette.types import Scope

    from src.gateway.auth import get_mcp_service

    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/test",
        "headers": [
            (b"authorization", b"Bearer wrong-key"),
            (b"x-mcp-request", b"true"),
        ],
    }
    request = Request(scope)

    with pytest.raises(Exception) as exc_info:
        await get_mcp_service(request)
    assert "Invalid MCP service key" in str(exc_info.value.detail)
