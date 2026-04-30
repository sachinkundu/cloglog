"""T-358 pin: two consecutive CHANGES_REQUESTED on the same PR -> one toast.

One ``CHANGES_REQUESTED`` is normal -- the agent will auto-fix on the next
nudge. Two consecutive turns means the agent can't auto-fix and operator
attention is needed.

Tracker is exercised in isolation (no event-loop fixture seeding required)
and the dispatcher is exercised on the resulting CHANGES_REQUESTED_REPEAT
event to assert the side effect.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.gateway.notification_listener import ChangesRequestedTracker, _dispatch
from src.shared.events import Event, EventType


def test_single_changes_requested_does_not_trigger_repeat():
    tracker = ChangesRequestedTracker()
    assert tracker.record("https://github.com/x/y/pull/1", "changes_requested") is False


def test_two_consecutive_changes_requested_triggers_repeat():
    tracker = ChangesRequestedTracker()
    pr = "https://github.com/x/y/pull/1"
    assert tracker.record(pr, "changes_requested") is False
    assert tracker.record(pr, "changes_requested") is True


def test_intervening_approval_resets_the_streak():
    tracker = ChangesRequestedTracker()
    pr = "https://github.com/x/y/pull/1"
    tracker.record(pr, "changes_requested")
    tracker.record(pr, "approved")
    # Second changes_requested after an approval is the start of a new streak,
    # not a repeat.
    assert tracker.record(pr, "changes_requested") is False


def test_streaks_are_tracked_per_pr():
    tracker = ChangesRequestedTracker()
    pr_a = "https://github.com/x/y/pull/1"
    pr_b = "https://github.com/x/y/pull/2"
    tracker.record(pr_a, "changes_requested")
    # PR B's first CR shouldn't piggyback on PR A's streak.
    assert tracker.record(pr_b, "changes_requested") is False
    assert tracker.record(pr_a, "changes_requested") is True


@pytest.mark.asyncio
async def test_changes_requested_repeat_event_fires_toast():
    event = Event(
        type=EventType.CHANGES_REQUESTED_REPEAT,
        project_id=uuid4(),
        data={"pr_url": "https://github.com/x/y/pull/1", "pr_number": 1},
    )
    mock_create_subprocess = AsyncMock()
    nl = "src.gateway.notification_listener"
    with (
        patch.dict(f"{nl}.os.environ", {"DISPLAY": ":1"}, clear=True),
        patch(f"{nl}.asyncio.create_subprocess_exec", mock_create_subprocess),
    ):
        await _dispatch(event, enabled=True)

    mock_create_subprocess.assert_awaited_once()
    body = mock_create_subprocess.call_args[0][2]
    assert "CHANGES_REQUESTED" in body
    assert "pull/1" in body
