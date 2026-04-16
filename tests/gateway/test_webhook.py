"""Tests for GitHub webhook endpoint and event parsing.

Covers: HMAC validation, event parsing for all types, dispatcher fan-out,
idempotency, and endpoint integration.
"""

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.gateway.webhook import parse_webhook_event, verify_signature
from src.gateway.webhook_dispatcher import (
    WebhookDispatcher,
    WebhookEvent,
    WebhookEventType,
)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "webhooks"
TEST_SECRET = "test-webhook-secret-123"


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / name).read_text())


def _make_signature(payload: bytes, secret: str) -> str:
    """Compute a valid HMAC-SHA256 signature for a payload."""
    digest = hmac.new(secret.encode("utf-8"), msg=payload, digestmod=hashlib.sha256).hexdigest()
    return f"sha256={digest}"


# ---------------------------------------------------------------------------
# HMAC Signature Validation
# ---------------------------------------------------------------------------


class TestVerifySignature:
    def test_valid_signature(self) -> None:
        payload = b'{"action": "opened"}'
        sig = _make_signature(payload, TEST_SECRET)
        assert verify_signature(payload, TEST_SECRET, sig) is True

    def test_invalid_signature(self) -> None:
        payload = b'{"action": "opened"}'
        assert verify_signature(payload, TEST_SECRET, "sha256=badhex") is False

    def test_empty_signature_header(self) -> None:
        payload = b'{"action": "opened"}'
        assert verify_signature(payload, TEST_SECRET, "") is False

    def test_wrong_secret(self) -> None:
        payload = b'{"action": "opened"}'
        sig = _make_signature(payload, "wrong-secret")
        assert verify_signature(payload, TEST_SECRET, sig) is False

    def test_tampered_payload(self) -> None:
        payload = b'{"action": "opened"}'
        sig = _make_signature(payload, TEST_SECRET)
        tampered = b'{"action": "closed"}'
        assert verify_signature(tampered, TEST_SECRET, sig) is False


# ---------------------------------------------------------------------------
# Event Parsing
# ---------------------------------------------------------------------------


class TestParseWebhookEvent:
    def test_pr_opened(self) -> None:
        payload = _load_fixture("pr_opened.json")
        event = parse_webhook_event("pull_request", "delivery-1", payload)
        assert event is not None
        assert event.type == WebhookEventType.PR_OPENED
        assert event.delivery_id == "delivery-1"
        assert event.repo_full_name == "sachinkundu/cloglog"
        assert event.pr_number == 42
        assert event.pr_url == "https://github.com/sachinkundu/cloglog/pull/42"
        assert event.head_branch == "wt-webhook-infra"
        assert event.base_branch == "main"
        assert event.sender == "cloglog-agent[bot]"

    def test_pr_synchronize(self) -> None:
        payload = _load_fixture("pr_synchronize.json")
        event = parse_webhook_event("pull_request", "delivery-2", payload)
        assert event is not None
        assert event.type == WebhookEventType.PR_SYNCHRONIZE
        assert event.pr_number == 42

    def test_pr_closed_merged(self) -> None:
        payload = _load_fixture("pr_closed_merged.json")
        event = parse_webhook_event("pull_request", "delivery-3", payload)
        assert event is not None
        assert event.type == WebhookEventType.PR_MERGED
        assert event.sender == "sachinkundu"

    def test_pr_closed_not_merged(self) -> None:
        payload = _load_fixture("pr_closed_not_merged.json")
        event = parse_webhook_event("pull_request", "delivery-4", payload)
        assert event is not None
        assert event.type == WebhookEventType.PR_CLOSED
        assert event.pr_number == 43

    def test_review_submitted(self) -> None:
        payload = _load_fixture("review_submitted_approved.json")
        event = parse_webhook_event("pull_request_review", "delivery-5", payload)
        assert event is not None
        assert event.type == WebhookEventType.REVIEW_SUBMITTED
        assert event.pr_number == 42
        assert event.sender == "sachinkundu"

    def test_review_changes_requested(self) -> None:
        payload = _load_fixture("review_submitted_changes_requested.json")
        event = parse_webhook_event("pull_request_review", "delivery-6", payload)
        assert event is not None
        assert event.type == WebhookEventType.REVIEW_SUBMITTED

    def test_review_comment_created(self) -> None:
        payload = _load_fixture("review_comment_created.json")
        event = parse_webhook_event("pull_request_review_comment", "delivery-rc-1", payload)
        assert event is not None
        assert event.type == WebhookEventType.REVIEW_COMMENT
        assert event.pr_number == 42
        assert event.sender == "sachinkundu"

    def test_review_comment_edited_returns_none(self) -> None:
        payload = _load_fixture("review_comment_created.json")
        payload["action"] = "edited"
        event = parse_webhook_event("pull_request_review_comment", "delivery-rc-2", payload)
        assert event is None

    def test_check_run_completed(self) -> None:
        payload = _load_fixture("check_run_completed_failure.json")
        event = parse_webhook_event("check_run", "delivery-7", payload)
        assert event is not None
        assert event.type == WebhookEventType.CHECK_RUN_COMPLETED
        assert event.pr_number == 42
        assert event.sender == "github-actions[bot]"
        assert event.pr_url == "https://github.com/sachinkundu/cloglog/pull/42"

    def test_unknown_event_type_returns_none(self) -> None:
        event = parse_webhook_event("issues", "delivery-8", {"action": "opened"})
        assert event is None

    def test_unknown_pr_action_returns_none(self) -> None:
        payload = _load_fixture("pr_opened.json")
        payload["action"] = "labeled"
        event = parse_webhook_event("pull_request", "delivery-9", payload)
        assert event is None

    def test_check_run_without_prs_returns_none(self) -> None:
        payload = {
            "action": "completed",
            "check_run": {
                "pull_requests": [],
                "conclusion": "success",
            },
            "repository": {"full_name": "sachinkundu/cloglog"},
            "sender": {"login": "github-actions[bot]"},
        }
        event = parse_webhook_event("check_run", "delivery-10", payload)
        assert event is None

    def test_pr_event_missing_pull_request_returns_none(self) -> None:
        payload = {
            "action": "opened",
            "repository": {"full_name": "sachinkundu/cloglog"},
            "sender": {"login": "someone"},
        }
        event = parse_webhook_event("pull_request", "delivery-11", payload)
        assert event is None

    def test_review_event_missing_pull_request_returns_none(self) -> None:
        payload = {
            "action": "submitted",
            "review": {"state": "approved", "body": "ok"},
            "repository": {"full_name": "sachinkundu/cloglog"},
            "sender": {"login": "someone"},
        }
        event = parse_webhook_event("pull_request_review", "delivery-12", payload)
        assert event is None


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


class TestWebhookDispatcher:
    def _make_event(self, delivery_id: str = "d-1") -> WebhookEvent:
        return WebhookEvent(
            type=WebhookEventType.PR_OPENED,
            delivery_id=delivery_id,
            repo_full_name="sachinkundu/cloglog",
            pr_number=42,
            pr_url="https://github.com/sachinkundu/cloglog/pull/42",
            head_branch="wt-test",
            base_branch="main",
            sender="test-user",
            raw={},
        )

    def _make_consumer(self, *, handles: bool = True) -> MagicMock:
        consumer = MagicMock()
        consumer.handles.return_value = handles
        consumer.handle = AsyncMock()
        return consumer

    @pytest.mark.asyncio
    async def test_dispatch_calls_matching_consumer(self) -> None:
        dispatcher = WebhookDispatcher()
        consumer = self._make_consumer(handles=True)
        dispatcher.register(consumer)

        event = self._make_event()
        await dispatcher.dispatch(event)

        import asyncio

        await asyncio.sleep(0.01)

        consumer.handles.assert_called_once_with(event)
        consumer.handle.assert_called_once_with(event)

    @pytest.mark.asyncio
    async def test_dispatch_skips_non_matching_consumer(self) -> None:
        dispatcher = WebhookDispatcher()
        consumer = self._make_consumer(handles=False)
        dispatcher.register(consumer)

        event = self._make_event()
        await dispatcher.dispatch(event)

        import asyncio

        await asyncio.sleep(0.01)

        consumer.handles.assert_called_once_with(event)
        consumer.handle.assert_not_called()

    @pytest.mark.asyncio
    async def test_idempotency_skips_duplicate_delivery(self) -> None:
        dispatcher = WebhookDispatcher()
        consumer = self._make_consumer(handles=True)
        dispatcher.register(consumer)

        event = self._make_event(delivery_id="dup-1")
        await dispatcher.dispatch(event)
        await dispatcher.dispatch(event)  # duplicate

        import asyncio

        await asyncio.sleep(0.01)

        consumer.handle.assert_called_once()

    @pytest.mark.asyncio
    async def test_different_delivery_ids_both_dispatched(self) -> None:
        dispatcher = WebhookDispatcher()
        consumer = self._make_consumer(handles=True)
        dispatcher.register(consumer)

        await dispatcher.dispatch(self._make_event(delivery_id="a"))
        await dispatcher.dispatch(self._make_event(delivery_id="b"))

        import asyncio

        await asyncio.sleep(0.01)

        assert consumer.handle.call_count == 2

    @pytest.mark.asyncio
    async def test_consumer_failure_is_isolated(self) -> None:
        dispatcher = WebhookDispatcher()

        failing_consumer = self._make_consumer(handles=True)
        failing_consumer.handle.side_effect = RuntimeError("boom")

        ok_consumer = self._make_consumer(handles=True)

        dispatcher.register(failing_consumer)
        dispatcher.register(ok_consumer)

        await dispatcher.dispatch(self._make_event(delivery_id="iso-1"))

        import asyncio

        await asyncio.sleep(0.01)

        failing_consumer.handle.assert_called_once()
        ok_consumer.handle.assert_called_once()

    @pytest.mark.asyncio
    async def test_seen_ids_eviction(self) -> None:
        dispatcher = WebhookDispatcher()
        dispatcher._max_seen = 10  # Small for testing

        for i in range(15):
            await dispatcher.dispatch(self._make_event(delivery_id=f"evict-{i}"))

        # After eviction, set should be smaller than max
        assert len(dispatcher._seen_delivery_ids) <= 10


# ---------------------------------------------------------------------------
# Endpoint Integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_endpoint_valid_signature(client: AsyncClient) -> None:
    """POST with valid HMAC signature returns 200."""
    payload = _load_fixture("pr_opened.json")
    body = json.dumps(payload).encode()
    sig = _make_signature(body, TEST_SECRET)

    with (
        patch("src.gateway.webhook.settings") as mock_settings,
        patch("src.gateway.webhook_dispatcher.webhook_dispatcher") as mock_dispatcher,
    ):
        mock_settings.github_webhook_secret = TEST_SECRET
        mock_dispatcher.dispatch = AsyncMock()
        response = await client.post(
            "/api/v1/webhooks/github",
            content=body,
            headers={
                "X-Hub-Signature-256": sig,
                "X-GitHub-Event": "pull_request",
                "X-GitHub-Delivery": "test-delivery-1",
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_webhook_endpoint_invalid_signature(client: AsyncClient) -> None:
    """POST with invalid HMAC signature returns 401."""
    payload = _load_fixture("pr_opened.json")
    body = json.dumps(payload).encode()

    with patch("src.gateway.webhook.settings") as mock_settings:
        mock_settings.github_webhook_secret = TEST_SECRET
        response = await client.post(
            "/api/v1/webhooks/github",
            content=body,
            headers={
                "X-Hub-Signature-256": "sha256=invalid",
                "X-GitHub-Event": "pull_request",
                "X-GitHub-Delivery": "test-delivery-2",
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_webhook_endpoint_missing_signature(client: AsyncClient) -> None:
    """POST without signature header returns 401."""
    payload = _load_fixture("pr_opened.json")
    body = json.dumps(payload).encode()

    with patch("src.gateway.webhook.settings") as mock_settings:
        mock_settings.github_webhook_secret = TEST_SECRET
        response = await client.post(
            "/api/v1/webhooks/github",
            content=body,
            headers={
                "X-GitHub-Event": "pull_request",
                "X-GitHub-Delivery": "test-delivery-3",
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_webhook_endpoint_empty_secret_rejects(client: AsyncClient) -> None:
    """If webhook secret is not configured, all requests are rejected."""
    payload = _load_fixture("pr_opened.json")
    body = json.dumps(payload).encode()

    with patch("src.gateway.webhook.settings") as mock_settings:
        mock_settings.github_webhook_secret = ""
        response = await client.post(
            "/api/v1/webhooks/github",
            content=body,
            headers={
                "X-Hub-Signature-256": "sha256=whatever",
                "X-GitHub-Event": "pull_request",
                "X-GitHub-Delivery": "test-delivery-4",
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 401
    assert "not configured" in response.json()["detail"]


@pytest.mark.asyncio
async def test_webhook_endpoint_unhandled_event_returns_ok(
    client: AsyncClient,
) -> None:
    """Unhandled event types still return 200 (we just don't dispatch them)."""
    payload = {"action": "created", "issue": {"number": 1}}
    body = json.dumps(payload).encode()
    sig = _make_signature(body, TEST_SECRET)

    with patch("src.gateway.webhook.settings") as mock_settings:
        mock_settings.github_webhook_secret = TEST_SECRET
        response = await client.post(
            "/api/v1/webhooks/github",
            content=body,
            headers={
                "X-Hub-Signature-256": sig,
                "X-GitHub-Event": "issues",
                "X-GitHub-Delivery": "test-delivery-5",
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_webhook_endpoint_bypasses_access_control(
    client: AsyncClient,
) -> None:
    """Webhook endpoint does not require Dashboard-Key or Bearer token."""
    payload = _load_fixture("pr_opened.json")
    body = json.dumps(payload).encode()
    sig = _make_signature(body, TEST_SECRET)

    from src.gateway.app import create_app

    app = create_app()

    with (
        patch("src.gateway.webhook.settings") as mock_settings,
        patch("src.gateway.webhook_dispatcher.webhook_dispatcher") as mock_dispatcher,
    ):
        mock_settings.github_webhook_secret = TEST_SECRET
        mock_dispatcher.dispatch = AsyncMock()
        # Client without Dashboard-Key to verify middleware bypass
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as bare_client:
            response = await bare_client.post(
                "/api/v1/webhooks/github",
                content=body,
                headers={
                    "X-Hub-Signature-256": sig,
                    "X-GitHub-Event": "pull_request",
                    "X-GitHub-Delivery": "test-delivery-6",
                    "Content-Type": "application/json",
                },
            )

    assert response.status_code == 200
