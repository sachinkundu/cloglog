"""Webhook event dispatcher — in-process async pub/sub for GitHub webhook events.

Fan-out webhook events to registered consumers. Same pattern as EventBus
in src/shared/events.py but for external GitHub events rather than internal
domain events.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from src.shared.log_event import log_event

logger = logging.getLogger(__name__)


class WebhookEventType(StrEnum):
    PR_OPENED = "pr_opened"
    PR_SYNCHRONIZE = "pr_synchronize"
    PR_CLOSED = "pr_closed"
    PR_MERGED = "pr_merged"
    REVIEW_SUBMITTED = "review_submitted"
    REVIEW_COMMENT = "review_comment"
    ISSUE_COMMENT = "issue_comment"
    CHECK_RUN_COMPLETED = "check_run_completed"


@dataclass(frozen=True)
class WebhookEvent:
    """Normalized internal event parsed from a GitHub webhook payload."""

    type: WebhookEventType
    delivery_id: str
    repo_full_name: str
    pr_number: int
    pr_url: str
    head_branch: str
    base_branch: str
    sender: str
    raw: dict[str, Any]


class WebhookConsumer(Protocol):
    """Interface for webhook event consumers."""

    def handles(self, event: WebhookEvent) -> bool:
        """Return True if this consumer wants to process this event."""
        ...

    async def handle(self, event: WebhookEvent) -> None:
        """Process the event. Exceptions are caught and logged by the dispatcher."""
        ...


class WebhookDispatcher:
    """Fan-out webhook events to registered consumers."""

    def __init__(self) -> None:
        self._consumers: list[WebhookConsumer] = []
        self._seen_delivery_ids: set[str] = set()
        self._max_seen = 10_000

    def register(self, consumer: WebhookConsumer) -> None:
        self._consumers.append(consumer)

    async def dispatch(self, event: WebhookEvent) -> None:
        # Idempotency: skip duplicate deliveries
        if event.delivery_id in self._seen_delivery_ids:
            logger.info("Skipping duplicate delivery %s", event.delivery_id)
            return
        self._seen_delivery_ids.add(event.delivery_id)
        if len(self._seen_delivery_ids) > self._max_seen:
            # Evict oldest entries — in practice duplicates arrive within seconds
            self._seen_delivery_ids = set(list(self._seen_delivery_ids)[self._max_seen // 2 :])

        pr = event.pr_number if event.pr_number else None
        log_event(
            logger,
            "webhook.received",
            delivery=event.delivery_id,
            event=event.type,
            repo=event.repo_full_name,
            pr=pr,
        )

        for consumer in self._consumers:
            if consumer.handles(event):
                asyncio.create_task(self._safe_handle(consumer, event))

    async def _safe_handle(self, consumer: WebhookConsumer, event: WebhookEvent) -> None:
        try:
            await consumer.handle(event)
            log_event(
                logger,
                "webhook.dispatched",
                delivery=event.delivery_id,
                consumer=type(consumer).__name__,
                result="ok",
            )
        except Exception:
            log_event(
                logger,
                "webhook.dispatched",
                delivery=event.delivery_id,
                consumer=type(consumer).__name__,
                result="error",
            )
            logger.exception(
                "Consumer %s failed on event %s (delivery=%s)",
                type(consumer).__name__,
                event.type,
                event.delivery_id,
            )


webhook_dispatcher = WebhookDispatcher()
