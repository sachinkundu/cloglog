"""T-358 pin: AGENT_BLOCKED dispatches one notify-send call.

Happy path for the new event class. The dispatcher must shell out to
``notify-send`` with title ``cloglog`` and a body that names the block
reason so the toast is actionable.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.shared.events import Event, EventType


@pytest.mark.asyncio
async def test_agent_blocked_event_fires_one_notify_send():
    event = Event(
        type=EventType.AGENT_BLOCKED,
        project_id=uuid4(),
        data={
            "reason": "mcp_unavailable",
            "worktree_path": "/tmp/wt-foo",
        },
    )
    mock_create_subprocess = AsyncMock()
    nl = "src.gateway.notification_listener"
    with (
        patch.dict(f"{nl}.os.environ", {"DISPLAY": ":1"}, clear=True),
        patch(f"{nl}.asyncio.create_subprocess_exec", mock_create_subprocess),
    ):
        from src.gateway.notification_listener import _dispatch

        await _dispatch(event, enabled=True)

    mock_create_subprocess.assert_awaited_once()
    args = mock_create_subprocess.call_args[0]
    assert args[0] == "notify-send"
    assert args[1] == "cloglog"
    body = args[2]
    assert "mcp_unavailable" in body
    assert "/tmp/wt-foo" in body


@pytest.mark.asyncio
async def test_agent_blocked_event_skipped_when_disabled():
    """Operator off-switch (``desktop_toast_enabled: false``) suppresses the toast."""
    event = Event(
        type=EventType.AGENT_BLOCKED,
        project_id=uuid4(),
        data={"reason": "mcp_unavailable"},
    )
    mock_create_subprocess = AsyncMock()
    nl = "src.gateway.notification_listener"
    with (
        patch.dict(f"{nl}.os.environ", {"DISPLAY": ":1"}, clear=True),
        patch(f"{nl}.asyncio.create_subprocess_exec", mock_create_subprocess),
    ):
        from src.gateway.notification_listener import _dispatch

        await _dispatch(event, enabled=False)

    mock_create_subprocess.assert_not_awaited()
