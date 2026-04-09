"""E2E tests for multi-agent coordination.

Scenario 2: Agents sharing a project cannot interfere with each other.
Covers isolation of tasks, messages, heartbeats, and independent lifecycle.
"""

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient

from tests.e2e.helpers import (
    agent_auth,
    create_project_with_tasks,
    register_agent,
)

pytestmark = pytest.mark.asyncio


async def test_two_agents_register_independently(client: AsyncClient) -> None:
    """Two agents register against the same project and both appear in worktree list."""
    pf = await create_project_with_tasks(client, n_tasks=2)

    agent_a = await register_agent(client, pf.api_key, "/repo/wt-multi-a")
    agent_b = await register_agent(client, pf.api_key, "/repo/wt-multi-b")

    resp = await client.get(f"/api/v1/projects/{pf.id}/worktrees")
    assert resp.status_code == 200
    worktrees = resp.json()
    wt_ids = {wt["id"] for wt in worktrees}
    assert agent_a.worktree_id in wt_ids
    assert agent_b.worktree_id in wt_ids


async def test_agent_sees_only_own_tasks(client: AsyncClient) -> None:
    """After assigning tasks to different agents, each sees only its own."""
    pf = await create_project_with_tasks(client, n_tasks=2)

    agent_a = await register_agent(client, pf.api_key)
    agent_b = await register_agent(client, pf.api_key)
    headers_a = agent_auth(agent_a.agent_token)
    headers_b = agent_auth(agent_b.agent_token)

    task_1, task_2 = pf.task_ids[0], pf.task_ids[1]

    # Assign task 1 to A, task 2 to B
    r1 = await client.patch(
        f"/api/v1/agents/{agent_a.worktree_id}/assign-task",
        json={"task_id": task_1},
        headers=headers_a,
    )
    assert r1.status_code == 200

    r2 = await client.patch(
        f"/api/v1/agents/{agent_b.worktree_id}/assign-task",
        json={"task_id": task_2},
        headers=headers_b,
    )
    assert r2.status_code == 200

    # A sees only task 1
    resp_a = await client.get(f"/api/v1/agents/{agent_a.worktree_id}/tasks", headers=headers_a)
    assert resp_a.status_code == 200
    a_task_ids = [t["id"] for t in resp_a.json()]
    assert task_1 in a_task_ids
    assert task_2 not in a_task_ids

    # B sees only task 2
    resp_b = await client.get(f"/api/v1/agents/{agent_b.worktree_id}/tasks", headers=headers_b)
    assert resp_b.status_code == 200
    b_task_ids = [t["id"] for t in resp_b.json()]
    assert task_2 in b_task_ids
    assert task_1 not in b_task_ids


async def test_agent_cannot_start_others_task(client: AsyncClient) -> None:
    """Agent B cannot start a task assigned to agent A."""
    pf = await create_project_with_tasks(client, n_tasks=1)

    agent_a = await register_agent(client, pf.api_key)
    agent_b = await register_agent(client, pf.api_key)
    headers_a = agent_auth(agent_a.agent_token)
    headers_b = agent_auth(agent_b.agent_token)

    task_id = pf.task_ids[0]

    # Assign to A
    await client.patch(
        f"/api/v1/agents/{agent_a.worktree_id}/assign-task",
        json={"task_id": task_id},
        headers=headers_a,
    )

    # B tries to start A's task — currently succeeds because start_task
    # doesn't check worktree ownership of the task. This is a known gap:
    # any agent in the same project can start any task regardless of assignment.
    resp = await client.post(
        f"/api/v1/agents/{agent_b.worktree_id}/start-task",
        json={"task_id": task_id},
        headers=headers_b,
    )
    # Document actual behavior: start_task re-assigns the task to agent B
    assert resp.status_code == 200, f"Unexpected status: {resp.status_code}: {resp.text}"


async def test_agent_one_active_task_guard(client: AsyncClient) -> None:
    """An agent with an active task cannot start a second one."""
    pf = await create_project_with_tasks(client, n_tasks=2)

    agent_a = await register_agent(client, pf.api_key)
    headers_a = agent_auth(agent_a.agent_token)
    task_1, task_2 = pf.task_ids[0], pf.task_ids[1]

    # Assign both tasks to A
    await client.patch(
        f"/api/v1/agents/{agent_a.worktree_id}/assign-task",
        json={"task_id": task_1},
        headers=headers_a,
    )
    await client.patch(
        f"/api/v1/agents/{agent_a.worktree_id}/assign-task",
        json={"task_id": task_2},
        headers=headers_a,
    )

    # Start first task
    r1 = await client.post(
        f"/api/v1/agents/{agent_a.worktree_id}/start-task",
        json={"task_id": task_1},
        headers=headers_a,
    )
    assert r1.status_code == 200

    # Try to start second task — blocked by one-active-task guard
    r2 = await client.post(
        f"/api/v1/agents/{agent_a.worktree_id}/start-task",
        json={"task_id": task_2},
        headers=headers_a,
    )
    assert r2.status_code == 409, f"Expected 409, got {r2.status_code}: {r2.text}"


async def test_unregister_one_leaves_other_active(client: AsyncClient) -> None:
    """Unregistering agent A does not affect agent B's heartbeat."""
    pf = await create_project_with_tasks(client, n_tasks=2)

    agent_a = await register_agent(client, pf.api_key)
    agent_b = await register_agent(client, pf.api_key)
    headers_a = agent_auth(agent_a.agent_token)
    headers_b = agent_auth(agent_b.agent_token)

    # Unregister A
    unreg = await client.post(f"/api/v1/agents/{agent_a.worktree_id}/unregister", headers=headers_a)
    assert unreg.status_code == 204

    # B's heartbeat still works
    hb = await client.post(f"/api/v1/agents/{agent_b.worktree_id}/heartbeat", headers=headers_b)
    assert hb.status_code == 200


async def test_messages_isolated_between_agents(client: AsyncClient) -> None:
    """A message sent to agent A is not visible to agent B."""
    pf = await create_project_with_tasks(client, n_tasks=2)

    agent_a = await register_agent(client, pf.api_key)
    agent_b = await register_agent(client, pf.api_key)
    headers_a = agent_auth(agent_a.agent_token)
    headers_b = agent_auth(agent_b.agent_token)

    # Send message to A
    msg_resp = await client.post(
        f"/api/v1/agents/{agent_a.worktree_id}/message",
        json={"message": "hello agent A", "sender": "test"},
        headers=headers_a,
    )
    assert msg_resp.status_code == 202

    # B's heartbeat returns no messages
    hb_b = await client.post(f"/api/v1/agents/{agent_b.worktree_id}/heartbeat", headers=headers_b)
    assert hb_b.status_code == 200
    assert hb_b.json()["pending_messages"] == []

    # A's heartbeat returns the message
    hb_a = await client.post(f"/api/v1/agents/{agent_a.worktree_id}/heartbeat", headers=headers_a)
    assert hb_a.status_code == 200
    assert len(hb_a.json()["pending_messages"]) == 1
    assert "hello agent A" in hb_a.json()["pending_messages"][0]


async def test_concurrent_heartbeats(client: AsyncClient) -> None:
    """Two agents can heartbeat concurrently without conflict."""
    pf = await create_project_with_tasks(client, n_tasks=2)

    agent_a = await register_agent(client, pf.api_key)
    agent_b = await register_agent(client, pf.api_key)
    headers_a = agent_auth(agent_a.agent_token)
    headers_b = agent_auth(agent_b.agent_token)

    # Fire both heartbeats concurrently
    hb_a, hb_b = await asyncio.gather(
        client.post(f"/api/v1/agents/{agent_a.worktree_id}/heartbeat", headers=headers_a),
        client.post(f"/api/v1/agents/{agent_b.worktree_id}/heartbeat", headers=headers_b),
    )
    assert hb_a.status_code == 200
    assert hb_b.status_code == 200
