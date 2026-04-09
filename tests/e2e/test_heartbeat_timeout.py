"""E2E tests for heartbeat timeout detection.

Scenario 8: Heartbeat timeout detects and handles stale sessions.
Uses direct DB access to manipulate timestamps and calls the
AgentService.check_heartbeat_timeouts() method directly.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.models import Session as AgentSession
from src.agent.repository import AgentRepository
from src.agent.services import AgentService
from src.board.repository import BoardRepository
from src.shared.config import settings
from src.shared.events import EventType, event_bus
from tests.e2e.helpers import (
    create_project_with_tasks,
    register_agent,
)

pytestmark = pytest.mark.asyncio


async def _make_heartbeat_stale(db_session: AsyncSession, wt_id: str, seconds_ago: int) -> None:
    """Set last_heartbeat to `seconds_ago` seconds in the past."""
    old_time = datetime.now(UTC) - timedelta(seconds=seconds_ago)
    await db_session.execute(
        update(AgentSession)
        .where(AgentSession.worktree_id == uuid.UUID(wt_id))
        .where(AgentSession.status == "active")
        .values(last_heartbeat=old_time)
    )
    await db_session.commit()


async def test_heartbeat_timeout_detection(client: AsyncClient, db_session: AsyncSession) -> None:
    """A stale session is detected by check_heartbeat_timeouts."""
    pf = await create_project_with_tasks(client, n_tasks=0)
    agent = await register_agent(client, pf.api_key)

    # Make the heartbeat stale
    await _make_heartbeat_stale(
        db_session,
        agent.worktree_id,
        settings.heartbeat_timeout_seconds + 10,
    )

    service = AgentService(AgentRepository(db_session), BoardRepository(db_session))
    timed_out = await service.check_heartbeat_timeouts()

    timed_out_strs = [str(wid) for wid in timed_out]
    assert agent.worktree_id in timed_out_strs


async def test_timeout_emits_offline_event(client: AsyncClient, db_session: AsyncSession) -> None:
    """Heartbeat timeout emits a WORKTREE_OFFLINE event with reason=heartbeat_timeout."""
    pf = await create_project_with_tasks(client, n_tasks=0)
    agent = await register_agent(client, pf.api_key)

    # Subscribe before making stale
    queue = event_bus.subscribe(uuid.UUID(pf.id))

    try:
        # Drain any pre-existing events (e.g. WORKTREE_ONLINE from registration)
        while not queue.empty():
            queue.get_nowait()

        await _make_heartbeat_stale(
            db_session,
            agent.worktree_id,
            settings.heartbeat_timeout_seconds + 10,
        )

        service = AgentService(AgentRepository(db_session), BoardRepository(db_session))
        await service.check_heartbeat_timeouts()

        # Collect events
        events = []
        for _ in range(10):
            try:
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
                events.append(event)
            except TimeoutError:
                break

        offline_events = [e for e in events if e.type == EventType.WORKTREE_OFFLINE]
        assert len(offline_events) >= 1, (
            f"Expected WORKTREE_OFFLINE event, got events: {[e.type for e in events]}"
        )

        offline = offline_events[0]
        assert offline.data["reason"] == "heartbeat_timeout"
        assert offline.data["worktree_id"] == agent.worktree_id
    finally:
        event_bus.unsubscribe(uuid.UUID(pf.id), queue)


async def test_active_session_not_timed_out(client: AsyncClient, db_session: AsyncSession) -> None:
    """A freshly heartbeated session is not detected as timed out."""
    pf = await create_project_with_tasks(client, n_tasks=0)
    agent = await register_agent(client, pf.api_key)

    # Send a fresh heartbeat
    hb = await client.post(f"/api/v1/agents/{agent.worktree_id}/heartbeat")
    assert hb.status_code == 200

    service = AgentService(AgentRepository(db_session), BoardRepository(db_session))
    timed_out = await service.check_heartbeat_timeouts()

    timed_out_strs = [str(wid) for wid in timed_out]
    assert agent.worktree_id not in timed_out_strs


async def test_timeout_cutoff_boundary(client: AsyncClient, db_session: AsyncSession) -> None:
    """Session at (timeout - 1)s is NOT timed out; at (timeout + 1)s IS timed out."""
    pf = await create_project_with_tasks(client, n_tasks=0)

    # Agent A: just inside the timeout window (should NOT be timed out)
    agent_a = await register_agent(client, pf.api_key)
    await _make_heartbeat_stale(
        db_session,
        agent_a.worktree_id,
        settings.heartbeat_timeout_seconds - 1,
    )

    # Agent B: just outside the timeout window (should be timed out)
    agent_b = await register_agent(client, pf.api_key)
    await _make_heartbeat_stale(
        db_session,
        agent_b.worktree_id,
        settings.heartbeat_timeout_seconds + 1,
    )

    service = AgentService(AgentRepository(db_session), BoardRepository(db_session))
    timed_out = await service.check_heartbeat_timeouts()

    timed_out_strs = [str(wid) for wid in timed_out]
    assert agent_a.worktree_id not in timed_out_strs, "Agent A should NOT be timed out"
    assert agent_b.worktree_id in timed_out_strs, "Agent B SHOULD be timed out"
