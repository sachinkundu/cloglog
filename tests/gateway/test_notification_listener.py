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


@pytest.mark.asyncio
async def test_listener_fires_notify_send_when_display_set():
    """_handle_review_event should call notify-send when DISPLAY env var is set."""
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

    mock_proc = MagicMock()
    mock_create_subprocess = AsyncMock(return_value=mock_proc)

    _nl = "src.gateway.notification_listener"
    with (
        patch(f"{_nl}.async_session_factory", mock_session_factory),
        patch(f"{_nl}.BoardRepository", return_value=mock_repo),
        patch(f"{_nl}.event_bus.publish", new_callable=AsyncMock),
        patch.dict(f"{_nl}.os.environ", {"DISPLAY": ":1"}, clear=True),
        patch(f"{_nl}.asyncio.create_subprocess_exec", mock_create_subprocess),
    ):
        from src.gateway import notification_listener

        await notification_listener._handle_review_event(event)

    mock_create_subprocess.assert_awaited_once()
    call_args = mock_create_subprocess.call_args[0]
    assert call_args[0] == "notify-send"
    assert call_args[1] == "cloglog"
    assert "T-42" in call_args[2]
    assert "Fix bug" in call_args[2]


@pytest.mark.asyncio
async def test_listener_skips_notify_send_when_no_display():
    """_handle_review_event should NOT call notify-send when DISPLAY is not set."""
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

    mock_create_subprocess = AsyncMock()

    _nl = "src.gateway.notification_listener"
    with (
        patch(f"{_nl}.async_session_factory", mock_session_factory),
        patch(f"{_nl}.BoardRepository", return_value=mock_repo),
        patch(f"{_nl}.event_bus.publish", new_callable=AsyncMock),
        patch.dict(f"{_nl}.os.environ", {}, clear=True),
        patch(f"{_nl}.asyncio.create_subprocess_exec", mock_create_subprocess),
    ):
        from src.gateway import notification_listener

        await notification_listener._handle_review_event(event)

    mock_create_subprocess.assert_not_awaited()
