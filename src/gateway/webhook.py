"""GitHub webhook endpoint — receives, validates, parses, and dispatches webhook events.

Authentication is via HMAC-SHA256 signature validation, not Bearer tokens.
This endpoint is exempt from ApiAccessControlMiddleware.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from src.gateway.webhook_dispatcher import WebhookEvent, WebhookEventType
from src.shared.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["webhooks"])


def verify_signature(payload_body: bytes, secret: str, signature_header: str) -> bool:
    """Verify GitHub webhook HMAC-SHA256 signature."""
    if not signature_header:
        return False
    expected = (
        "sha256="
        + hmac.new(
            secret.encode("utf-8"),
            msg=payload_body,
            digestmod=hashlib.sha256,
        ).hexdigest()
    )
    return hmac.compare_digest(expected, signature_header)


def parse_webhook_event(
    event_type: str, delivery_id: str, payload: dict[str, Any]
) -> WebhookEvent | None:
    """Parse a GitHub webhook payload into a typed WebhookEvent.

    Returns None for event types we don't handle.
    """
    if event_type == "pull_request":
        action = payload.get("action", "")
        pr = payload.get("pull_request")
        if pr is None:
            return None

        if action == "opened":
            wh_type = WebhookEventType.PR_OPENED
        elif action == "synchronize":
            wh_type = WebhookEventType.PR_SYNCHRONIZE
        elif action == "closed":
            wh_type = WebhookEventType.PR_MERGED if pr.get("merged") else WebhookEventType.PR_CLOSED
        else:
            return None

        return WebhookEvent(
            type=wh_type,
            delivery_id=delivery_id,
            repo_full_name=payload["repository"]["full_name"],
            pr_number=pr["number"],
            pr_url=pr["html_url"],
            head_branch=pr["head"]["ref"],
            base_branch=pr["base"]["ref"],
            sender=payload["sender"]["login"],
            raw=payload,
        )

    if event_type == "pull_request_review":
        pr = payload.get("pull_request")
        if pr is None:
            return None

        return WebhookEvent(
            type=WebhookEventType.REVIEW_SUBMITTED,
            delivery_id=delivery_id,
            repo_full_name=payload["repository"]["full_name"],
            pr_number=pr["number"],
            pr_url=pr["html_url"],
            head_branch=pr["head"]["ref"],
            base_branch=pr["base"]["ref"],
            sender=payload["sender"]["login"],
            raw=payload,
        )

    if event_type == "pull_request_review_comment":
        action = payload.get("action", "")
        if action != "created":
            return None  # Only notify on new comments, not edits/deletes
        pr = payload.get("pull_request")
        if pr is None:
            return None

        return WebhookEvent(
            type=WebhookEventType.REVIEW_COMMENT,
            delivery_id=delivery_id,
            repo_full_name=payload["repository"]["full_name"],
            pr_number=pr["number"],
            pr_url=pr["html_url"],
            head_branch=pr["head"]["ref"],
            base_branch=pr["base"]["ref"],
            sender=payload["sender"]["login"],
            raw=payload,
        )

    if event_type == "issue_comment":
        action = payload.get("action", "")
        if action != "created":
            return None
        issue = payload.get("issue")
        if issue is None or "pull_request" not in issue:
            return None  # Plain issue comment, not a PR comment

        return WebhookEvent(
            type=WebhookEventType.ISSUE_COMMENT,
            delivery_id=delivery_id,
            repo_full_name=payload["repository"]["full_name"],
            pr_number=issue["number"],
            pr_url=issue["pull_request"]["html_url"],
            head_branch="",
            base_branch="",
            sender=payload["sender"]["login"],
            raw=payload,
        )

    if event_type == "check_run":
        prs = payload.get("check_run", {}).get("pull_requests", [])
        if not prs:
            return None
        pr = prs[0]
        return WebhookEvent(
            type=WebhookEventType.CHECK_RUN_COMPLETED,
            delivery_id=delivery_id,
            repo_full_name=payload["repository"]["full_name"],
            pr_number=pr["number"],
            pr_url=f"https://github.com/{payload['repository']['full_name']}/pull/{pr['number']}",
            head_branch=pr["head"]["ref"],
            base_branch=pr["base"]["ref"],
            sender=payload["sender"]["login"],
            raw=payload,
        )

    return None


@router.post("/webhooks/github")
async def receive_webhook(request: Request) -> dict[str, str]:
    """Receive and dispatch GitHub webhook events."""
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")

    if not settings.github_webhook_secret:
        raise HTTPException(status_code=401, detail="Webhook secret not configured") from None

    if not verify_signature(body, settings.github_webhook_secret, signature):
        raise HTTPException(status_code=401, detail="Invalid signature") from None

    event_type = request.headers.get("X-GitHub-Event", "")
    delivery_id = request.headers.get("X-GitHub-Delivery", "")
    payload = await request.json()

    event = parse_webhook_event(event_type, delivery_id, payload)
    if event is not None:
        from src.gateway.webhook_dispatcher import webhook_dispatcher

        await webhook_dispatcher.dispatch(event)
    else:
        logger.debug("Ignoring unhandled webhook: %s/%s", event_type, payload.get("action"))

    return {"status": "ok"}
