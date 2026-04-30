"""T-358 pin: AGENT_UNREGISTERED toasts only on known-non-clean reasons.

Codex round 1 caught the original failure mode: the public unregister API has
no ``reason`` parameter, so a normal post-merge agent exit publishes
``AGENT_UNREGISTERED`` with ``reason=None``. The listener's filter MUST treat
``None`` as a clean shutdown (silent), and toast only on the explicit
non-clean values (``force_unregistered``, ``heartbeat_timeout``).

Without this filter the operator would get a desktop toast on every
successful merge -- the exact noise problem T-358 is meant to remove.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.shared.events import Event, EventType


def _make_event(reason):
    data = {"worktree_id": str(uuid4()), "worktree_path": "/tmp/wt-foo"}
    if reason is not None:
        data["reason"] = reason
    return Event(type=EventType.AGENT_UNREGISTERED, project_id=uuid4(), data=data)


@pytest.mark.asyncio
async def test_clean_unregister_does_not_toast():
    """Default public-API unregister has no reason -- must stay silent."""
    mock_create_subprocess = AsyncMock()
    nl = "src.gateway.notification_listener"
    with (
        patch.dict(f"{nl}.os.environ", {"DISPLAY": ":1"}, clear=True),
        patch(f"{nl}.asyncio.create_subprocess_exec", mock_create_subprocess),
    ):
        from src.gateway.notification_listener import _dispatch

        await _dispatch(_make_event(None), enabled=True)

    mock_create_subprocess.assert_not_awaited()


@pytest.mark.asyncio
async def test_force_unregister_toasts():
    mock_create_subprocess = AsyncMock()
    nl = "src.gateway.notification_listener"
    with (
        patch.dict(f"{nl}.os.environ", {"DISPLAY": ":1"}, clear=True),
        patch(f"{nl}.asyncio.create_subprocess_exec", mock_create_subprocess),
    ):
        from src.gateway.notification_listener import _dispatch

        await _dispatch(_make_event("force_unregistered"), enabled=True)

    mock_create_subprocess.assert_awaited_once()
    body = mock_create_subprocess.call_args[0][2]
    assert "force_unregistered" in body
    assert "/tmp/wt-foo" in body


@pytest.mark.asyncio
async def test_heartbeat_timeout_toasts():
    mock_create_subprocess = AsyncMock()
    nl = "src.gateway.notification_listener"
    with (
        patch.dict(f"{nl}.os.environ", {"DISPLAY": ":1"}, clear=True),
        patch(f"{nl}.asyncio.create_subprocess_exec", mock_create_subprocess),
    ):
        from src.gateway.notification_listener import _dispatch

        await _dispatch(_make_event("heartbeat_timeout"), enabled=True)

    mock_create_subprocess.assert_awaited_once()


@pytest.mark.asyncio
async def test_unknown_reason_does_not_toast():
    """Unknown reasons fall through to silent -- the allowlist is the source of truth."""
    mock_create_subprocess = AsyncMock()
    nl = "src.gateway.notification_listener"
    with (
        patch.dict(f"{nl}.os.environ", {"DISPLAY": ":1"}, clear=True),
        patch(f"{nl}.asyncio.create_subprocess_exec", mock_create_subprocess),
    ):
        from src.gateway.notification_listener import _dispatch

        await _dispatch(_make_event("some-future-reason"), enabled=True)

    mock_create_subprocess.assert_not_awaited()


@pytest.mark.asyncio
async def test_off_switch_suppresses_non_clean_toast():
    """desktop_toast_enabled: false suppresses even non-clean reasons."""
    mock_create_subprocess = AsyncMock()
    nl = "src.gateway.notification_listener"
    with (
        patch.dict(f"{nl}.os.environ", {"DISPLAY": ":1"}, clear=True),
        patch(f"{nl}.asyncio.create_subprocess_exec", mock_create_subprocess),
    ):
        from src.gateway.notification_listener import _dispatch

        await _dispatch(_make_event("force_unregistered"), enabled=False)

    mock_create_subprocess.assert_not_awaited()
