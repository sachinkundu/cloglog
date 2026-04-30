"""T-358 pin: ci_not_green for >15 min -> single AUTO_MERGE_STALLED toast.

The StallDebouncer holds the per-PR clock. It must:
  * not toast on the first poll (stall starts now),
  * toast exactly once when the threshold is crossed,
  * stay silent on subsequent polls until ``clear`` is called,
  * scope state per-PR.

The dispatcher then routes the resulting AUTO_MERGE_STALLED event to
``notify-send`` with a body that names the PR and the stall duration.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.gateway.notification_listener import StallDebouncer, _dispatch
from src.shared.events import Event, EventType


def test_first_poll_does_not_trip():
    clock = iter([0.0])
    deb = StallDebouncer(threshold_seconds=900.0, clock=lambda: next(clock))
    assert deb.record_pending("pr1") is False


def test_threshold_crossed_trips_exactly_once():
    times = iter([0.0, 100.0, 901.0, 1500.0, 2000.0])
    deb = StallDebouncer(threshold_seconds=900.0, clock=lambda: next(times))
    assert deb.record_pending("pr1") is False  # t=0
    assert deb.record_pending("pr1") is False  # t=100, still under
    assert deb.record_pending("pr1") is True  # t=901, crossed
    assert deb.record_pending("pr1") is False  # t=1500, already toasted
    assert deb.record_pending("pr1") is False  # t=2000, still suppressed


def test_clear_resets_and_allows_a_future_stall_toast():
    times = iter([0.0, 1000.0, 2000.0, 3000.0])
    deb = StallDebouncer(threshold_seconds=900.0, clock=lambda: next(times))
    assert deb.record_pending("pr1") is False  # t=0
    assert deb.record_pending("pr1") is True  # t=1000
    deb.clear("pr1")
    assert deb.record_pending("pr1") is False  # t=2000, fresh window
    assert deb.record_pending("pr1") is True  # t=3000, crossed again


def test_per_pr_scoping():
    times = iter([0.0, 100.0, 901.0, 950.0])
    deb = StallDebouncer(threshold_seconds=900.0, clock=lambda: next(times))
    assert deb.record_pending("pr1") is False  # t=0
    assert deb.record_pending("pr2") is False  # t=100 -- separate clock
    assert deb.record_pending("pr1") is True  # t=901 -- pr1 crossed
    assert deb.record_pending("pr2") is False  # t=950 -- pr2 still inside its window


@pytest.mark.asyncio
async def test_auto_merge_stalled_event_fires_toast():
    event = Event(
        type=EventType.AUTO_MERGE_STALLED,
        project_id=uuid4(),
        data={
            "pr_url": "https://github.com/x/y/pull/1",
            "pr_number": 1,
            "stall_minutes": 15,
        },
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
    assert "Auto-merge" in body
    assert "pull/1" in body
    assert "15" in body
