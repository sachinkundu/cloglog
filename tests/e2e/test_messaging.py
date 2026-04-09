"""E2E tests for cross-session messaging.

Tests message queuing, delivery via heartbeat, ordering,
error handling, and task assignment notifications.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.e2e.helpers import (
    agent_auth,
    create_project_with_tasks,
    register_agent,
)

pytestmark = pytest.mark.asyncio


async def test_send_message_queued(client: AsyncClient) -> None:
    """Sending a message to a registered agent returns 202 (queued)."""
    pf = await create_project_with_tasks(client, n_tasks=0)
    agent = await register_agent(client, pf.api_key)

    resp = await client.post(
        f"/api/v1/agents/{agent.worktree_id}/message",
        json={"message": "hello", "sender": "test"},
    )
    assert resp.status_code == 202


async def test_heartbeat_drains_messages(client: AsyncClient) -> None:
    """First heartbeat delivers the message; second heartbeat returns empty."""
    pf = await create_project_with_tasks(client, n_tasks=0)
    agent = await register_agent(client, pf.api_key)

    # Send a message
    await client.post(
        f"/api/v1/agents/{agent.worktree_id}/message",
        json={"message": "drain-test", "sender": "test"},
    )

    # First heartbeat: message delivered
    headers = agent_auth(agent.agent_token)
    hb1 = await client.post(f"/api/v1/agents/{agent.worktree_id}/heartbeat", headers=headers)
    assert hb1.status_code == 200
    messages1 = hb1.json()["pending_messages"]
    assert len(messages1) == 1
    assert "drain-test" in messages1[0]

    # Second heartbeat: no more messages
    hb2 = await client.post(f"/api/v1/agents/{agent.worktree_id}/heartbeat", headers=headers)
    assert hb2.status_code == 200
    assert hb2.json()["pending_messages"] == []


async def test_message_delivery_order(client: AsyncClient) -> None:
    """Multiple messages are delivered in chronological order."""
    pf = await create_project_with_tasks(client, n_tasks=0)
    agent = await register_agent(client, pf.api_key)

    # Send 3 messages
    for i in range(3):
        await client.post(
            f"/api/v1/agents/{agent.worktree_id}/message",
            json={"message": f"msg-{i}", "sender": "test"},
        )

    # Heartbeat drains all 3
    headers = agent_auth(agent.agent_token)
    hb = await client.post(f"/api/v1/agents/{agent.worktree_id}/heartbeat", headers=headers)
    assert hb.status_code == 200
    messages = hb.json()["pending_messages"]
    assert len(messages) == 3

    # Verify order (messages are formatted as "[sender] message")
    assert "msg-0" in messages[0]
    assert "msg-1" in messages[1]
    assert "msg-2" in messages[2]


async def test_message_to_nonexistent_worktree(client: AsyncClient) -> None:
    """Sending a message to a non-existent worktree returns 404."""
    random_id = str(uuid.uuid4())
    resp = await client.post(
        f"/api/v1/agents/{random_id}/message",
        json={"message": "hello?", "sender": "test"},
    )
    assert resp.status_code == 404


async def test_task_assignment_sends_notification(client: AsyncClient) -> None:
    """Assigning a task to an agent queues a notification message."""
    pf = await create_project_with_tasks(client, n_tasks=1)
    agent = await register_agent(client, pf.api_key)

    task_id = pf.task_ids[0]
    headers = agent_auth(agent.agent_token)

    # Drain any registration messages first
    await client.post(f"/api/v1/agents/{agent.worktree_id}/heartbeat", headers=headers)

    # Assign task
    assign_resp = await client.patch(
        f"/api/v1/agents/{agent.worktree_id}/assign-task",
        json={"task_id": task_id},
        headers=headers,
    )
    assert assign_resp.status_code == 200

    # Heartbeat should contain assignment notification
    hb = await client.post(f"/api/v1/agents/{agent.worktree_id}/heartbeat", headers=headers)
    assert hb.status_code == 200
    messages = hb.json()["pending_messages"]
    assert len(messages) >= 1
    assert any("New task assigned" in m for m in messages), (
        f"Expected 'New task assigned' in messages, got: {messages}"
    )
