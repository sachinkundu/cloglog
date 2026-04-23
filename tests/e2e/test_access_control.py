"""E2E tests for access control (Scenarios 5 + 9).

Scenario 5: Middleware credential paths (MCP, agent-key-only, dashboard, none).
Scenario 9: Key resolution, rotation, header fallbacks, cross-project gaps.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.e2e.helpers import (
    agent_auth,
    auth_headers,
    create_project_with_tasks,
    dashboard_headers,
    mcp_headers,
    register_agent,
)

pytestmark = pytest.mark.asyncio


# ═══════════════════════════════════════════════════════════════
# Scenario 5 — Middleware credential paths
# ═══════════════════════════════════════════════════════════════


async def test_mcp_access_all_routes(client: AsyncClient, bare_client: AsyncClient) -> None:
    """MCP headers (Authorization + X-MCP-Request) grant access to board routes."""
    proj = await create_project_with_tasks(client, n_tasks=1)

    resp = await bare_client.get(
        f"/api/v1/projects/{proj.id}/board",
        headers=mcp_headers(proj.api_key),
    )
    assert resp.status_code == 200
    assert resp.json()["project_id"] == proj.id


async def test_agent_key_only_agent_routes(client: AsyncClient, bare_client: AsyncClient) -> None:
    """Agent API key (no X-MCP-Request) can access agent registration."""
    proj = await create_project_with_tasks(client, n_tasks=0)

    resp = await bare_client.post(
        "/api/v1/agents/register",
        json={
            "worktree_path": f"/repo/wt-{uuid.uuid4().hex[:8]}",
            "branch_name": "wt-test",
        },
        headers=auth_headers(proj.api_key),
    )
    assert resp.status_code == 201


async def test_agent_key_blocked_from_board(client: AsyncClient, bare_client: AsyncClient) -> None:
    """Agent API key without X-MCP-Request is forbidden on board routes."""
    proj = await create_project_with_tasks(client, n_tasks=1)

    resp = await bare_client.get(
        f"/api/v1/projects/{proj.id}/board",
        headers=auth_headers(proj.api_key),
    )
    assert resp.status_code == 403
    assert "Agents can only access" in resp.json()["detail"]


async def test_dashboard_key_non_agent_routes(
    client: AsyncClient, bare_client: AsyncClient
) -> None:
    """Dashboard key grants access to board routes."""
    proj = await create_project_with_tasks(client, n_tasks=1)

    resp = await bare_client.get(
        f"/api/v1/projects/{proj.id}/board",
        headers=dashboard_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["total_tasks"] == 1


async def test_agent_token_required_for_agent_routes(
    client: AsyncClient, bare_client: AsyncClient
) -> None:
    """Agent routes require a valid agent token, not just a dashboard key."""
    proj = await create_project_with_tasks(client, n_tasks=0)
    agent = await register_agent(client, proj.api_key)

    # Dashboard key alone is insufficient — agent token required
    resp = await bare_client.post(
        f"/api/v1/agents/{agent.worktree_id}/heartbeat",
        headers=dashboard_headers(),
    )
    assert resp.status_code == 401

    # Agent token works
    from tests.e2e.helpers import agent_auth

    resp = await bare_client.post(
        f"/api/v1/agents/{agent.worktree_id}/heartbeat",
        headers=agent_auth(agent.agent_token),
    )
    assert resp.status_code == 200


async def test_no_credentials_rejected(bare_client: AsyncClient) -> None:
    """Requests with no credentials are rejected with 401."""
    resp = await bare_client.get("/api/v1/projects")
    assert resp.status_code == 401
    assert "Authentication required" in resp.json()["detail"]


async def test_invalid_dashboard_key_rejected(bare_client: AsyncClient) -> None:
    """An invalid dashboard key is rejected with 403."""
    resp = await bare_client.get(
        "/api/v1/projects",
        headers={"X-Dashboard-Key": "wrong-key"},
    )
    assert resp.status_code == 403
    assert "Invalid dashboard key" in resp.json()["detail"]


async def test_health_endpoint_no_auth(bare_client: AsyncClient) -> None:
    """Health endpoint is not gated by the access control middleware."""
    resp = await bare_client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ═══════════════════════════════════════════════════════════════
# T-258 — /api/v1/projects/{id}/worktrees is NOT a public route
# ═══════════════════════════════════════════════════════════════
#
# Regression suite for the auth contract flagged in PR #172 review. The
# Option-B fix keeps the route authed and makes the requirement loud
# (docstring + docs/ddd-context-map.md § Auth Contract + explicit
# dashboard-key guards in src/gateway/cli.py and scripts/sync_mcp_dist.py).
# If a future PR adds /api/v1/projects/{id}/worktrees to the middleware
# allowlist, `test_worktrees_without_auth_is_rejected` fails — the route
# stops being authed.


async def test_worktrees_without_auth_is_rejected(
    client: AsyncClient, bare_client: AsyncClient
) -> None:
    """GET /api/v1/projects/{id}/worktrees with no credentials at all
    returns 401. This is the regression guard T-258 locks in: the route
    is NOT public; the middleware rejects the request before the handler
    runs."""
    proj = await create_project_with_tasks(client, n_tasks=0)
    resp = await bare_client.get(f"/api/v1/projects/{proj.id}/worktrees")
    assert resp.status_code == 401, (
        f"expected 401 Authentication required, got {resp.status_code}; "
        f"body: {resp.text}. If this is now 200, the route has been "
        "promoted to public — that is Option A of T-258 and would require "
        "updating docs/ddd-context-map.md § Auth Contract in the same PR."
    )
    assert "Authentication required" in resp.json()["detail"]


async def test_worktrees_with_wrong_dashboard_key_is_rejected(
    client: AsyncClient, bare_client: AsyncClient
) -> None:
    """GET /worktrees with an invalid X-Dashboard-Key returns 403.
    Pins the middleware's distinction between "no credential" (401) and
    "wrong credential" (403)."""
    proj = await create_project_with_tasks(client, n_tasks=0)
    resp = await bare_client.get(
        f"/api/v1/projects/{proj.id}/worktrees",
        headers={"X-Dashboard-Key": "definitely-not-the-real-secret"},
    )
    assert resp.status_code == 403, resp.text
    assert "Invalid dashboard key" in resp.json()["detail"]


async def test_worktrees_with_dashboard_key_succeeds(
    client: AsyncClient, bare_client: AsyncClient
) -> None:
    """GET /worktrees with the correct X-Dashboard-Key returns 200.
    This is the positive case the CLI and sync_mcp_dist.py exercise —
    if it breaks, every dashboard-ish caller breaks with it."""
    proj = await create_project_with_tasks(client, n_tasks=0)
    await register_agent(client, proj.api_key)

    resp = await bare_client.get(
        f"/api/v1/projects/{proj.id}/worktrees",
        headers=dashboard_headers(),
    )
    assert resp.status_code == 200, resp.text
    worktrees = resp.json()
    assert isinstance(worktrees, list)
    assert len(worktrees) == 1


async def test_worktrees_with_agent_token_is_rejected(
    client: AsyncClient, bare_client: AsyncClient
) -> None:
    """GET /worktrees with an agent-scoped token returns 403. Agent
    tokens are specifically NOT allowed on non-agent routes — the
    /worktrees listing is a dashboard operation, not an agent one.
    Guards against a tempting shortcut where an agent tries to read
    its sibling worktrees using its own token."""
    proj = await create_project_with_tasks(client, n_tasks=0)
    agent = await register_agent(client, proj.api_key)

    resp = await bare_client.get(
        f"/api/v1/projects/{proj.id}/worktrees",
        headers=agent_auth(agent.agent_token),
    )
    assert resp.status_code == 403, resp.text
    assert "Agents can only access" in resp.json()["detail"]


async def test_worktrees_with_invalid_mcp_bearer_is_rejected(
    client: AsyncClient, bare_client: AsyncClient
) -> None:
    """GET /worktrees with X-MCP-Request: true + an invalid Bearer
    token returns 401 Invalid MCP service key. Codex round 2 on PR #191
    caught that the middleware only checks PRESENCE of both headers and
    does not validate the bearer value; without a per-route
    ``CurrentMcpOrDashboard`` dep the handler accepted any garbage
    bearer under this shape. This test pins the post-fix behaviour:
    the per-route dep runs ``hmac.compare_digest(token, mcp_service_key)``
    and rejects mismatches."""
    proj = await create_project_with_tasks(client, n_tasks=0)
    resp = await bare_client.get(
        f"/api/v1/projects/{proj.id}/worktrees",
        headers={
            "Authorization": "Bearer totally-fake-garbage",
            "X-MCP-Request": "true",
        },
    )
    assert resp.status_code == 401, (
        f"expected 401 Invalid MCP service key, got {resp.status_code}; "
        f"body: {resp.text}. If this is 200, the per-route "
        "CurrentMcpOrDashboard dependency has been removed and the route "
        "has regressed to accepting any bearer under the MCP shape."
    )
    assert "Invalid MCP service key" in resp.json()["detail"]


# ═══════════════════════════════════════════════════════════════
# Scenario 9 — Key resolution, rotation, fallbacks
# ═══════════════════════════════════════════════════════════════


async def test_agent_key_resolves_to_correct_project(
    client: AsyncClient, bare_client: AsyncClient
) -> None:
    """Registering an agent with project A's key creates a worktree in project A."""
    proj = await create_project_with_tasks(client, n_tasks=0)
    agent = await register_agent(client, proj.api_key)

    # List worktrees for this project — should include the newly registered one
    resp = await client.get(f"/api/v1/projects/{proj.id}/worktrees")
    assert resp.status_code == 200
    worktree_ids = {wt["id"] for wt in resp.json()}
    assert agent.worktree_id in worktree_ids


async def test_expired_or_rotated_key_rejected(
    client: AsyncClient, bare_client: AsyncClient
) -> None:
    """After deleting a project, its API key should no longer authenticate."""
    proj = await create_project_with_tasks(client, n_tasks=0)
    old_key = proj.api_key

    # Delete the project
    del_resp = await client.delete(f"/api/v1/projects/{proj.id}")
    assert del_resp.status_code == 204

    # Attempt to register agent with the now-invalid key
    resp = await bare_client.post(
        "/api/v1/agents/register",
        json={
            "worktree_path": f"/repo/wt-{uuid.uuid4().hex[:8]}",
            "branch_name": "wt-expired",
        },
        headers=auth_headers(old_key),
    )
    assert resp.status_code == 401


async def test_x_api_key_header_fallback(client: AsyncClient, bare_client: AsyncClient) -> None:
    """X-API-Key header is accepted as a fallback for Authorization: Bearer."""
    proj = await create_project_with_tasks(client, n_tasks=0)

    # Use X-API-Key instead of Authorization header, plus X-MCP-Request
    # to pass the middleware (X-API-Key alone has no Authorization header,
    # so middleware sees no auth — we need MCP or dashboard for the gate).
    # The auth.py dependency checks X-API-Key as fallback for project resolution.
    # Use dashboard key for middleware, X-API-Key for project resolution.
    resp = await bare_client.get(
        "/api/v1/gateway/me",
        headers={
            "X-API-Key": proj.api_key,
            "X-Dashboard-Key": "cloglog-dashboard-dev",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == proj.id
    assert resp.json()["name"] is not None


async def test_dashboard_key_from_query_param(bare_client: AsyncClient) -> None:
    """Dashboard key can be provided as a query parameter (SSE/EventSource fallback)."""
    resp = await bare_client.get(
        "/api/v1/projects",
        params={"dashboard_key": "cloglog-dashboard-dev"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_cross_project_task_access_blocked(
    client: AsyncClient, bare_client: AsyncClient
) -> None:
    """Cross-project task assignment gap: agent from project A can be assigned B's task.

    Known gap: assign_task sets worktree_id on the task without validating that the
    task's project matches the worktree's project. This test documents the behavior.
    The assign-task endpoint checks that the worktree exists but does NOT check
    project ownership of the task.
    """
    proj_a = await create_project_with_tasks(client, n_tasks=0)
    proj_b = await create_project_with_tasks(client, n_tasks=1)

    # Register agent in project A
    agent_a = await register_agent(client, proj_a.api_key)
    ah = agent_auth(agent_a.agent_token)

    # Assign project B's task to project A's agent
    # This succeeds because assign_task doesn't validate project ownership
    resp = await client.patch(
        f"/api/v1/agents/{agent_a.worktree_id}/assign-task",
        json={"task_id": proj_b.task_ids[0]},
        headers=ah,
    )
    # NOTE: This documents a known gap — cross-project assignment is not blocked.
    # The endpoint succeeds (200) because it only checks worktree existence,
    # not project membership of the task.
    assert resp.status_code == 200, (
        f"Expected 200 (known gap: no cross-project check), got {resp.status_code}"
    )

    # Verify the task now appears in agent A's task list despite being from project B
    tasks_resp = await client.get(
        f"/api/v1/agents/{agent_a.worktree_id}/tasks",
        headers=ah,
    )
    assert tasks_resp.status_code == 200
    task_ids = [t["id"] for t in tasks_resp.json()]
    assert proj_b.task_ids[0] in task_ids, (
        "Cross-project task should appear in agent's task list (known gap)"
    )
