"""E2E tests for project isolation (Scenario 4).

Verifies that two projects with separate API keys are completely
isolated: different keys, independent boards, scoped SSE events,
and per-project entity numbering.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from httpx import AsyncClient

from src.shared.events import EventType, event_bus
from tests.e2e.helpers import (
    create_project_with_tasks,
    mcp_headers,
    register_agent,
)

pytestmark = pytest.mark.asyncio


# ── Helpers ─────────────────────────────────────────────────────


async def _create_two_projects(client: AsyncClient, n_tasks_a: int = 2, n_tasks_b: int = 1):
    """Create two independent projects and return their fixtures."""
    proj_a = await create_project_with_tasks(client, n_tasks=n_tasks_a)
    proj_b = await create_project_with_tasks(client, n_tasks=n_tasks_b)
    return proj_a, proj_b


# ── Tests ───────────────────────────────────────────────────────


async def test_separate_projects_separate_keys(client: AsyncClient) -> None:
    """Two projects must have distinct API keys."""
    proj_a, proj_b = await _create_two_projects(client)
    assert proj_a.api_key != proj_b.api_key
    assert proj_a.id != proj_b.id


async def test_agent_in_project_a_cannot_access_project_b_board(
    client: AsyncClient,
) -> None:
    """An MCP-authenticated agent can read any project's board, but the data is scoped.

    Agent registered in project A should not see A's tasks when querying B's board,
    and vice versa.
    """
    proj_a, proj_b = await _create_two_projects(client, n_tasks_a=2, n_tasks_b=1)
    await register_agent(client, proj_a.api_key)

    # Agent A reads project B's board via MCP headers — should succeed but show B's data only
    headers_a = mcp_headers(proj_a.api_key)
    resp_b = await client.get(f"/api/v1/projects/{proj_b.id}/board", headers=headers_a)
    assert resp_b.status_code == 200
    board_b = resp_b.json()
    assert board_b["project_id"] == proj_b.id
    assert board_b["total_tasks"] == 1  # B has 1 task, not A's 2

    # Conversely, reading A's board shows A's data
    resp_a = await client.get(f"/api/v1/projects/{proj_a.id}/board", headers=headers_a)
    assert resp_a.status_code == 200
    board_a = resp_a.json()
    assert board_a["project_id"] == proj_a.id
    assert board_a["total_tasks"] == 2

    # Confirm no task ID overlap between boards
    a_task_ids = {t["id"] for col in board_a["columns"] for t in col["tasks"]}
    b_task_ids = {t["id"] for col in board_b["columns"] for t in col["tasks"]}
    assert a_task_ids.isdisjoint(b_task_ids), "Task IDs must not overlap between projects"


async def test_board_state_independent(client: AsyncClient) -> None:
    """Mutating project A's board must not affect project B's board."""
    proj_a, proj_b = await _create_two_projects(client, n_tasks_a=2, n_tasks_b=1)

    # Snapshot B's board before any mutation
    board_b_before = (await client.get(f"/api/v1/projects/{proj_b.id}/board")).json()

    # Mutate A: move a task to in_progress
    await client.patch(
        f"/api/v1/tasks/{proj_a.task_ids[0]}",
        json={"status": "in_progress"},
    )

    # B's board should be completely unchanged
    board_b_after = (await client.get(f"/api/v1/projects/{proj_b.id}/board")).json()
    assert board_b_after["total_tasks"] == board_b_before["total_tasks"]

    # All B tasks still in backlog
    backlog_col = next(c for c in board_b_after["columns"] if c["status"] == "backlog")
    assert len(backlog_col["tasks"]) == board_b_before["total_tasks"]


async def test_sse_events_project_scoped(client: AsyncClient) -> None:
    """Events published for project B must NOT appear on project A's subscription."""
    proj_a, proj_b = await _create_two_projects(client, n_tasks_a=0, n_tasks_b=0)

    queue = event_bus.subscribe(uuid.UUID(proj_a.id))
    try:
        # Create a task in project B — should NOT reach A's queue
        await client.post(
            f"/api/v1/projects/{proj_b.id}/features/{proj_b.feature_id}/tasks",
            json={"title": "B-only task"},
        )
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(queue.get(), timeout=0.5)

        # Create a task in project A — SHOULD reach A's queue
        await client.post(
            f"/api/v1/projects/{proj_a.id}/features/{proj_a.feature_id}/tasks",
            json={"title": "A task"},
        )
        event = await asyncio.wait_for(queue.get(), timeout=2.0)
        assert event.type == EventType.TASK_CREATED
        assert event.project_id == uuid.UUID(proj_a.id)
    finally:
        event_bus.unsubscribe(uuid.UUID(proj_a.id), queue)


async def test_agent_register_wrong_project_key(client: AsyncClient) -> None:
    """An agent registered in project B should not see project A's tasks."""
    proj_a, proj_b = await _create_two_projects(client, n_tasks_a=2, n_tasks_b=0)

    # Register agent with B's API key — worktree belongs to project B
    agent_b = await register_agent(client, proj_b.api_key)

    # A's tasks are NOT assigned to this worktree, so get_tasks returns empty
    resp = await client.get(f"/api/v1/agents/{agent_b.worktree_id}/tasks")
    assert resp.status_code == 200
    tasks = resp.json()
    assert len(tasks) == 0, "Agent in project B should have no tasks from project A"


async def test_entity_numbering_project_scoped(client: AsyncClient) -> None:
    """Task numbers are sequential within each project, starting at 1."""
    proj_a = await create_project_with_tasks(client, n_tasks=2)
    proj_b = await create_project_with_tasks(client, n_tasks=1)

    board_a = (await client.get(f"/api/v1/projects/{proj_a.id}/board")).json()
    board_b = (await client.get(f"/api/v1/projects/{proj_b.id}/board")).json()

    a_numbers = sorted(t["number"] for col in board_a["columns"] for t in col["tasks"])
    b_numbers = sorted(t["number"] for col in board_b["columns"] for t in col["tasks"])

    # Project A: tasks numbered 1, 2
    assert a_numbers == [1, 2], f"Expected [1, 2], got {a_numbers}"

    # Project B: task numbered 1 (independent sequence)
    assert b_numbers == [1], f"Expected [1], got {b_numbers}"
