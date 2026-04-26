"""T-260: ReviewLoop emits ``review_codex_turn_started`` on codex claims.

The dashboard's "codex reviewed" badge is driven by a boolean projection
from ``pr_review_turns``. To ensure the badge flips visibly in real time,
the loop publishes an ``Event(REVIEW_CODEX_TURN_STARTED)`` whenever it
enters a codex turn. Opencode turns do NOT emit — only codex flips the
badge per T-260's scope.

Pin tests:
  - codex stage + successful claim_turn → event published on the bus.
  - opencode stage → NO codex event published.
  - event payload carries pr_url / pr_number / head_sha / turn_number.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.shared.events import Event, EventType, event_bus
from tests.gateway.test_review_loop import (
    FakeRegistry,
    StubReviewer,
    _make_loop,
    _ok_result,
)

_PATCH_POST_REVIEW = "src.gateway.review_loop.post_review"


def _record_events() -> tuple[list[Event], object]:
    """Subscribe a queue-like recorder. Returns (events_list, unsubscribe_handle)."""
    captured: list[Event] = []

    class _Rec:
        def put_nowait(self, event: Event) -> None:
            captured.append(event)

    # Attach to the global event bus's internal global subscribers list.
    event_bus._global_subscribers.append(_Rec())  # type: ignore[arg-type]
    return captured, _Rec  # handle returned only so caller can pop on teardown


class TestReviewCodexTurnStartedSSEEvent:
    @pytest.mark.asyncio
    async def test_codex_stage_emits_event_on_claim(self) -> None:
        captured, _ = _record_events()

        stub = StubReviewer(
            responses=[(_ok_result(status="no_further_concerns"), 1.0, False)],
        )
        registry = FakeRegistry()
        loop = _make_loop(stub, max_turns=2, registry=registry, stage="codex")

        with patch(_PATCH_POST_REVIEW, new=AsyncMock(return_value=True)):
            await loop.run(diff="some diff")

        codex_events = [e for e in captured if e.type == EventType.REVIEW_CODEX_TURN_STARTED]
        assert len(codex_events) >= 1, (
            f"Expected at least one REVIEW_CODEX_TURN_STARTED event; saw: "
            f"{[e.type.value for e in captured]}"
        )
        ev = codex_events[0]
        # Payload pinning — T-260 frontend expects pr_url for routing.
        assert ev.data.get("pr_url") == "https://github.com/owner/repo/pull/1"
        assert ev.data.get("pr_number") == 1
        assert ev.data.get("turn_number") == 1
        assert "head_sha" in ev.data

    @pytest.mark.asyncio
    async def test_opencode_stage_does_not_emit_codex_event(self) -> None:
        """Opencode turns deliberately don't flip the badge — no SSE either."""
        captured, _ = _record_events()

        stub = StubReviewer(
            responses=[(_ok_result(status="no_further_concerns"), 1.0, False)],
        )
        registry = FakeRegistry()
        loop = _make_loop(stub, max_turns=2, registry=registry, stage="opencode")

        with patch(_PATCH_POST_REVIEW, new=AsyncMock(return_value=True)):
            await loop.run(diff="some diff")

        codex_events = [e for e in captured if e.type == EventType.REVIEW_CODEX_TURN_STARTED]
        assert codex_events == [], (
            "Opencode stage must NOT emit REVIEW_CODEX_TURN_STARTED — "
            f"saw: {[e.data for e in codex_events]}"
        )

    @pytest.mark.asyncio
    async def test_codex_event_carries_project_id(self) -> None:
        """The SSE stream routes by project_id, so it must be on the Event."""
        captured, _ = _record_events()

        stub = StubReviewer(
            responses=[(_ok_result(status="no_further_concerns"), 1.0, False)],
        )
        registry = FakeRegistry()
        loop = _make_loop(stub, max_turns=1, registry=registry, stage="codex")

        with patch(_PATCH_POST_REVIEW, new=AsyncMock(return_value=True)):
            await loop.run(diff="some diff")

        codex_events = [e for e in captured if e.type == EventType.REVIEW_CODEX_TURN_STARTED]
        assert codex_events
        assert isinstance(codex_events[0].project_id, uuid.UUID)
