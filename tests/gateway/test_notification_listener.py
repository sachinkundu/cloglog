"""Tests for the notification listener background task."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.shared.events import Event, EventType


def _make_event(project_id, task_id):
    return Event(
        type=EventType.TASK_STATUS_CHANGED,
        project_id=project_id,
        data={"task_id": str(task_id), "new_status": "review"},
    )


def _make_task(task_id):
    return type(
        "MockTask",
        (),
        {"id": task_id, "title": "Fix bug", "number": 42, "feature_id": uuid4()},
    )()


def _make_notif(project_id, task_id):
    return type(
        "MockNotif",
        (),
        {
            "id": uuid4(),
            "project_id": project_id,
            "task_id": task_id,
            "task_title": "Fix bug",
            "task_number": 42,
            "read": False,
        },
    )()


@pytest.mark.asyncio
async def test_listener_creates_notification_on_review():
    """_handle_review_event should call create_notification and publish NOTIFICATION_CREATED."""
    project_id = uuid4()
    task_id = uuid4()
    event = _make_event(project_id, task_id)

    mock_task = _make_task(task_id)
    mock_notif = _make_notif(project_id, task_id)

    mock_repo = MagicMock()
    mock_repo.get_task = AsyncMock(return_value=mock_task)
    mock_repo.create_notification = AsyncMock(return_value=mock_notif)

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_session_factory = MagicMock(return_value=mock_session)

    _nl = "src.gateway.notification_listener"
    with (
        patch(f"{_nl}.async_session_factory", mock_session_factory),
        patch(f"{_nl}.BoardRepository", return_value=mock_repo),
        patch(f"{_nl}.event_bus.publish", new_callable=AsyncMock) as mock_publish,
        patch.dict(f"{_nl}.os.environ", {}, clear=True),
    ):
        from src.gateway.notification_listener import _handle_review_event

        await _handle_review_event(event)

    mock_repo.create_notification.assert_awaited_once_with(
        project_id=project_id,
        task_id=task_id,
        task_title="Fix bug",
        task_number=42,
    )
    mock_publish.assert_awaited_once()
    published_event = mock_publish.call_args[0][0]
    assert published_event.type == EventType.NOTIFICATION_CREATED
    assert published_event.project_id == project_id
    assert published_event.data["task_title"] == "Fix bug"
    assert published_event.data["task_number"] == 42


# T-358: notify-send no longer fires on TASK_STATUS_CHANGED -> review (only the
# persisted Notification row + NOTIFICATION_CREATED SSE for the dashboard bell).
# The replacement absence-pin lives in
# tests/gateway/test_notification_listener_does_not_toast_on_review_transition.py
# and the new toast classes are pinned in the sibling
# test_notification_listener_toasts_on_*.py files.
