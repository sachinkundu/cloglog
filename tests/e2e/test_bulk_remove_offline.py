"""E2E tests for bulk removal of offline agents.

Covers: the dashboard-facing endpoint that removes all offline
worktree records for a project.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.repository import AgentRepository
from tests.e2e.helpers import (
    create_project_with_tasks,
    register_agent,
)

pytestmark = pytest.mark.asyncio


async def test_bulk_remove_deletes_offline_agents(client: AsyncClient) -> None:
    """Bulk remove deletes all offline agents and returns the count."""
    pf = await create_project_with_tasks(client, n_tasks=0)

    # Register three agents (all online)
    await register_agent(client, pf.api_key)
    await register_agent(client, pf.api_key)
    await register_agent(client, pf.api_key)

    # With all three online, bulk-remove-offline should delete none.
    # (Driving worktrees to offline state is covered by the companion test
    # below, which uses the repository directly — the dashboard shutdown
    # endpoint flips a flag and writes the inbox but does not force offline.)
    resp = await client.post(f"/api/v1/projects/{pf.id}/worktrees/remove-offline")
    assert resp.status_code == 200
    assert resp.json()["removed_count"] == 0

    # All three still exist
    wt_resp = await client.get(f"/api/v1/projects/{pf.id}/worktrees")
    assert len(wt_resp.json()) == 3


async def test_bulk_remove_offline_with_db(client: AsyncClient, db_session: AsyncSession) -> None:
    """Offline agents are removed; online agents are kept."""
    pf = await create_project_with_tasks(client, n_tasks=0)

    online = await register_agent(client, pf.api_key)
    offline1 = await register_agent(client, pf.api_key)
    offline2 = await register_agent(client, pf.api_key)

    # Mark two agents offline via the repository
    repo = AgentRepository(db_session)
    await repo.set_worktree_offline(uuid.UUID(offline1.worktree_id))
    await repo.set_worktree_offline(uuid.UUID(offline2.worktree_id))

    resp = await client.post(f"/api/v1/projects/{pf.id}/worktrees/remove-offline")
    assert resp.status_code == 200
    assert resp.json()["removed_count"] == 2

    # Only the online agent remains
    wt_resp = await client.get(f"/api/v1/projects/{pf.id}/worktrees")
    worktrees = wt_resp.json()
    assert len(worktrees) == 1
    assert worktrees[0]["id"] == online.worktree_id
    assert worktrees[0]["status"] == "online"


async def test_bulk_remove_is_project_scoped(client: AsyncClient, db_session: AsyncSession) -> None:
    """Removing offline agents in project A does not affect project B."""
    pf_a = await create_project_with_tasks(client, n_tasks=0)
    pf_b = await create_project_with_tasks(client, n_tasks=0)

    agent_a = await register_agent(client, pf_a.api_key)
    agent_b = await register_agent(client, pf_b.api_key)

    # Mark both offline
    repo = AgentRepository(db_session)
    await repo.set_worktree_offline(uuid.UUID(agent_a.worktree_id))
    await repo.set_worktree_offline(uuid.UUID(agent_b.worktree_id))

    # Remove only from project A
    resp = await client.post(f"/api/v1/projects/{pf_a.id}/worktrees/remove-offline")
    assert resp.status_code == 200
    assert resp.json()["removed_count"] == 1

    # Project B's agent is untouched
    wt_resp = await client.get(f"/api/v1/projects/{pf_b.id}/worktrees")
    worktrees = wt_resp.json()
    assert len(worktrees) == 1
    assert worktrees[0]["id"] == agent_b.worktree_id
