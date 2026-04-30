"""T-358 pin: TASK_STATUS_CHANGED -> review must NOT shell out to notify-send.

Regression we are fixing: every PR open fired a desktop toast, training the
operator to ignore them. The persisted Notification row + NOTIFICATION_CREATED
SSE for the dashboard bell stay; only the ``notify-send`` call goes away.

Absence-pin form: mock ``asyncio.create_subprocess_exec`` and assert it was
NOT awaited (per CLAUDE.md "Absence-pins on antipattern substrings collide
with documentation that names the antipattern" -- we pin behavior, not text).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.shared.events import Event, EventType


@pytest.mark.asyncio
async def test_review_transition_creates_row_and_sse_but_no_toast():
    project_id = uuid4()
    task_id = uuid4()
    event = Event(
        type=EventType.TASK_STATUS_CHANGED,
        project_id=project_id,
        data={"task_id": str(task_id), "new_status": "review"},
    )

    mock_task = type(
        "MockTask",
        (),
        {"id": task_id, "title": "Fix bug", "number": 42, "feature_id": uuid4()},
    )()
    mock_notif = type(
        "MockNotif",
        (),
        {"id": uuid4(), "task_id": task_id, "task_title": "Fix bug", "task_number": 42},
    )()

    mock_repo = MagicMock()
    mock_repo.get_task = AsyncMock(return_value=mock_task)
    mock_repo.create_notification = AsyncMock(return_value=mock_notif)

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session_factory = MagicMock(return_value=mock_session)

    mock_create_subprocess = AsyncMock()

    nl = "src.gateway.notification_listener"
    with (
        patch(f"{nl}.async_session_factory", mock_session_factory),
        patch(f"{nl}.BoardRepository", return_value=mock_repo),
        patch(f"{nl}.event_bus.publish", new_callable=AsyncMock) as mock_publish,
        # DISPLAY set + PYTEST_CURRENT_TEST cleared would normally fire the
        # toast under the pre-T-358 code; we set both so the absence-pin
        # would catch any future reintroduction of the inline call.
        patch.dict(f"{nl}.os.environ", {"DISPLAY": ":1"}, clear=True),
        patch(f"{nl}.asyncio.create_subprocess_exec", mock_create_subprocess),
    ):
        from src.gateway.notification_listener import _dispatch

        await _dispatch(event, enabled=True)

    # Row + SSE happened.
    mock_repo.create_notification.assert_awaited_once()
    mock_publish.assert_awaited_once()
    published = mock_publish.call_args[0][0]
    assert published.type == EventType.NOTIFICATION_CREATED

    # Toast did NOT.
    mock_create_subprocess.assert_not_awaited()
