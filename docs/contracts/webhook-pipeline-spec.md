# GitHub Webhook Pipeline — Design Spec

## Overview

This spec covers three interdependent features that add webhook-driven automation to cloglog:

1. **F-47: Webhook Ingestion Infrastructure** — receive, validate, parse, and dispatch GitHub webhook events
2. **F-36: PR Review Webhook Server** — Claude-powered automated code review triggered by PR events
3. **F-46: Agent PR Event Notifications** — route PR events to the relevant worktree agent, replacing polling

F-47 is the foundation. F-36 and F-46 are independent consumers that plug into F-47's dispatcher.

### Current Pain Point

Agents currently poll for PR state every 5 minutes via `/loop 5m` using the github-bot skill. This is wasteful, adds latency (up to 5 minutes to notice a merge or review comment), and consumes Claude API tokens on every poll iteration. Webhook-driven notifications eliminate all three problems.

## Architecture

### Bounded Context Ownership

**Decision: The webhook infrastructure lives in the Gateway context.**

Rationale:
- Gateway already owns API composition, authentication, and SSE fan-out (see `docs/ddd-context-map.md`)
- Webhook ingestion is an inbound API concern — it receives external HTTP requests, validates them, and routes them to internal consumers
- Gateway already has the `event_bus` integration for SSE fan-out
- The webhook endpoint is analogous to the existing SSE stream endpoint — both are Gateway responsibilities

**Update 2026-04-23 (T-248):** The review engine WAS a Gateway module at this spec's original writing; when T-248 added persistence for per-turn idempotency (`pr_review_turns`), that state was extracted into its own bounded context `src/review/` — because Gateway owns no tables (see `docs/ddd-context-map.md § Bounded Contexts`). The webhook infrastructure (endpoint, dispatcher, consumers) still lives in Gateway; `review_engine.py` and `review_loop.py` remain Gateway modules that talk to the Review context through `src.review.services.make_review_turn_registry(session)` — an Open Host Service factory returning `IReviewTurnRegistry`. Do NOT import `src.review.models` or `src.review.repository` from Gateway; lazy imports inside functions also count as DDD violations (PR #187 round 2 CRITICAL).

Original paragraph kept for historical context: "The review engine is a new module within Gateway, not a new bounded context. It is a consumer of webhook events and a caller of external APIs (Claude, GitHub). It does not own any domain models. If it grows complex enough to warrant its own context, it can be extracted later, but starting with a new bounded context for a single consumer function is over-engineering." That decision was reversed once persistence was added.

**File structure:**
```
src/gateway/
  webhook.py             # F-47: Webhook endpoint, HMAC validation, event parsing
  webhook_dispatcher.py  # F-47: In-process event dispatcher
  webhook_consumers.py   # F-46: Agent notification consumer
  review_engine.py       # F-36: webhook → diff → per-stage ReviewLoop plumbing
  review_loop.py         # T-248: shared per-reviewer loop + CodexReviewer / OpencodeReviewer adapters
  github_token.py        # Shared: async GitHub App token generation (claude, codex, opencode)
src/review/
  models.py              # T-248: PrReviewTurn SQLAlchemy model + PrReviewTurnStatus
  interfaces.py          # T-248: IReviewTurnRegistry Protocol + ReviewTurnSnapshot
  repository.py          # T-248: ReviewTurnRepository (ON CONFLICT DO NOTHING claim)
  services.py            # T-248: make_review_turn_registry(session) — Open Host Service
  schemas.py             # T-248: Pydantic shapes for API surface
```

### Event Flow Overview

```
GitHub ──webhook──> cloudflared tunnel ──> FastAPI /api/v1/webhooks/github
                                              │
                                    HMAC-SHA256 validation
                                              │
                                    Parse into typed WebhookEvent
                                              │
                                    WebhookDispatcher.dispatch()
                                              │
                              ┌───────────────┼───────────────┐
                              ▼               ▼               ▼
                     F-36: ReviewEngine   F-46: AgentNotifier  (future consumers)
                              │               │
                     Claude API → review   Resolve PR → task → worktree
                     GitHub API ← comments  Append to agent inbox file
```

### Dispatcher Design

**Decision: In-process async pub/sub, same pattern as the existing `EventBus`.**

Rationale:
- The existing `EventBus` in `src/shared/events.py` already provides in-process pub/sub with `asyncio.Queue` per subscriber. This pattern works and is well-understood in the codebase.
- A database queue (e.g., PostgreSQL LISTEN/NOTIFY or a jobs table) adds complexity for zero benefit at this scale. cloglog runs as a single FastAPI process on one machine.
- The webhook endpoint returns 200 immediately, then dispatches to consumers asynchronously via `asyncio.create_task`. This meets GitHub's 10-second response requirement.

**Consumer registration is static, at startup.** Consumers are registered in the `lifespan` function of `app.py`, not dynamically. There are only two consumers (review engine and agent notifier), and they are known at compile time.

```python
# src/gateway/webhook_dispatcher.py

from __future__ import annotations
import asyncio
import logging
from collections import OrderedDict
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class WebhookEventType(StrEnum):
    PR_OPENED = "pr_opened"
    PR_SYNCHRONIZE = "pr_synchronize"
    PR_CLOSED = "pr_closed"
    PR_MERGED = "pr_merged"            # Derived from pr_closed + merged=True
    REVIEW_SUBMITTED = "review_submitted"
    CHECK_RUN_COMPLETED = "check_run_completed"


@dataclass(frozen=True)
class WebhookEvent:
    """Normalized internal event parsed from a GitHub webhook payload."""
    type: WebhookEventType
    delivery_id: str                   # X-GitHub-Delivery header (idempotency key)
    repo_full_name: str                # e.g. "sachinkundu/cloglog"
    pr_number: int
    pr_url: str                        # html_url of the PR
    head_branch: str                   # PR source branch
    base_branch: str                   # PR target branch
    sender: str                        # GitHub username who triggered
    raw: dict[str, Any]                # Full original payload for consumers that need it


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
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._max_seen = 10_000

    def register(self, consumer: WebhookConsumer) -> None:
        self._consumers.append(consumer)

    async def dispatch(self, event: WebhookEvent) -> None:
        # Idempotency: skip duplicate deliveries
        if event.delivery_id in self._seen:
            logger.info("Skipping duplicate delivery %s", event.delivery_id)
            return
        self._seen[event.delivery_id] = None
        # Evict oldest when over capacity — OrderedDict preserves insertion order
        while len(self._seen) > self._max_seen:
            self._seen.popitem(last=False)

        for consumer in self._consumers:
            if consumer.handles(event):
                asyncio.create_task(self._safe_handle(consumer, event))

    async def _safe_handle(self, consumer: WebhookConsumer, event: WebhookEvent) -> None:
        try:
            await consumer.handle(event)
        except Exception:
            logger.exception(
                "Consumer %s failed on event %s (delivery=%s)",
                type(consumer).__name__, event.type, event.delivery_id,
            )


# Module-level singleton, like event_bus
webhook_dispatcher = WebhookDispatcher()
```

## F-47: Webhook Ingestion Infrastructure

### Data Flow

1. GitHub sends POST to `https://cloglog.voxdez.com/api/v1/webhooks/github` (via cloudflared tunnel)
2. FastAPI route receives the request
3. HMAC-SHA256 validation against `GITHUB_WEBHOOK_SECRET` env var
4. Parse `X-GitHub-Event` header to determine event type
5. Parse JSON payload into a typed `WebhookEvent`
6. Return `{"status": "ok"}` immediately (200)
7. Dispatch to consumers asynchronously

### API Contract

#### `POST /api/v1/webhooks/github`

**Authentication:** HMAC-SHA256 signature validation (not Bearer token). This endpoint is exempt from the `ApiAccessControlMiddleware` because webhooks come from GitHub, not from agents or the dashboard.

**Headers (from GitHub):**
- `X-Hub-Signature-256: sha256=<hex_digest>` — HMAC signature
- `X-GitHub-Event: pull_request | pull_request_review | check_run` — event type
- `X-GitHub-Delivery: <uuid>` — unique delivery ID for idempotency
- `Content-Type: application/json`

**Response:** `200 {"status": "ok"}` on valid signature, `401 {"detail": "Invalid signature"}` on failure, `400` on unparseable payload.

**Middleware exemption:** The `ApiAccessControlMiddleware` in `src/gateway/app.py` (line 38) gates all `/api/v1/` paths. The webhook endpoint uses HMAC auth, not Bearer tokens or dashboard keys. Add the webhook path to the early-return check at line 59:

```python
# In ApiAccessControlMiddleware.dispatch():
# Only gate /api/v1/ routes; health checks and webhooks pass through
if not path.startswith("/api/v1/") or path.startswith("/api/v1/webhooks/"):
    return await call_next(request)
```

Using `startswith("/api/v1/webhooks/")` instead of exact match allows future webhook endpoints (e.g., Slack, Linear) without additional middleware changes.

### Webhook Endpoint Implementation

```python
# src/gateway/webhook.py

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from src.gateway.webhook_dispatcher import WebhookDispatcher, WebhookEvent, WebhookEventType
from src.shared.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["webhooks"])


def verify_signature(payload_body: bytes, secret: str, signature_header: str) -> bool:
    """Verify GitHub webhook HMAC-SHA256 signature."""
    if not signature_header or not secret:
        return False
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"),
        msg=payload_body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def parse_webhook_event(
    event_type: str, delivery_id: str, payload: dict[str, Any]
) -> WebhookEvent | None:
    """Parse a GitHub webhook payload into a typed WebhookEvent.

    Returns None for event types we don't handle.
    """
    if event_type == "pull_request":
        action = payload.get("action", "")
        pr = payload["pull_request"]
        pr_url = pr["html_url"]

        if action == "opened":
            wh_type = WebhookEventType.PR_OPENED
        elif action == "synchronize":
            wh_type = WebhookEventType.PR_SYNCHRONIZE
        elif action == "closed":
            wh_type = WebhookEventType.PR_MERGED if pr.get("merged") else WebhookEventType.PR_CLOSED
        else:
            return None  # We don't handle other PR actions (labeled, assigned, etc.)

        return WebhookEvent(
            type=wh_type,
            delivery_id=delivery_id,
            repo_full_name=payload["repository"]["full_name"],
            pr_number=pr["number"],
            pr_url=pr_url,
            head_branch=pr["head"]["ref"],
            base_branch=pr["base"]["ref"],
            sender=payload["sender"]["login"],
            raw=payload,
        )

    if event_type == "pull_request_review":
        action = payload.get("action", "")
        # Only handle "submitted" — ignore "edited" and "dismissed"
        if action != "submitted":
            return None
        pr = payload["pull_request"]
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

    if event_type == "check_run":
        action = payload.get("action", "")
        if action != "completed":
            return None
        check_run = payload.get("check_run", {})
        prs = check_run.get("pull_requests", [])
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

    if not verify_signature(body, settings.github_webhook_secret, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

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
```

### Database Schema

**Decision: No new tables for F-47.**

Rationale:
- Webhook events are transient. They arrive, get dispatched to consumers, and are done.
- For audit/replay, GitHub retains all webhook deliveries for 3 days and provides a redelivery API. Building our own event store duplicates GitHub's capability.
- If we later need replay (e.g., for debugging), we add a `webhook_deliveries` table then. YAGNI for now.
- The idempotency check uses an in-memory `OrderedDict`. Since cloglog runs as a single process and GitHub does not auto-retry failed deliveries, the only duplicate scenario is manual redelivery, which the in-memory check handles fine.

### Configuration Changes

Add to `src/shared/config.py`:

```python
class Settings(BaseSettings):
    # ... existing fields ...
    github_webhook_secret: str = ""  # REQUIRED for production; empty = reject all (fail-closed)
```

**Note:** When `github_webhook_secret` is empty, `verify_signature()` returns `False` (the `if not secret: return False` check). This is fail-closed — no requests are accepted without a configured secret.

Add to `.env.example`:

```
GITHUB_WEBHOOK_SECRET=your-secret-here
```

### Event Types and Parsing

| GitHub Event | Action | Internal Type | Consumers |
|---|---|---|---|
| `pull_request` | `opened` | `PR_OPENED` | F-36 (review), F-46 (notify agent) |
| `pull_request` | `synchronize` | `PR_SYNCHRONIZE` | F-36 (re-review), F-46 (notify agent) |
| `pull_request` | `closed` + `merged=true` | `PR_MERGED` | F-46 (notify agent) |
| `pull_request` | `closed` + `merged=false` | `PR_CLOSED` | F-46 (notify agent) |
| `pull_request_review` | `submitted` | `REVIEW_SUBMITTED` | F-46 (notify agent) |
| `check_run` | `completed` | `CHECK_RUN_COMPLETED` | F-46 (notify agent) |

**Ignored actions:** `pull_request_review` with `edited` or `dismissed` (not actionable for agents). `check_run` with `created`, `rerequested`, `requested_action` (only `completed` matters). `pull_request` with `labeled`, `assigned`, `review_requested`, etc.

### Cloudflared Setup

**Decision: Named tunnel using `cloglog.voxdez.com` subdomain on the existing `voxdez.com` Cloudflare-managed domain.**

The `voxdez.com` domain is already on Cloudflare. We create a `cloglog` subdomain to route GitHub webhooks to the dev machine. Cloudflared creates an outbound-only encrypted tunnel from the dev machine to Cloudflare's edge, which proxies inbound webhook requests back to localhost.

#### One-Time Setup

```bash
# 1. Install cloudflared
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o cloudflared.deb
sudo dpkg -i cloudflared.deb

# 2. Authenticate with Cloudflare account (select voxdez.com when prompted)
cloudflared tunnel login

# 3. Create a named tunnel
cloudflared tunnel create cloglog-webhooks

# 4. Route DNS — creates a CNAME record for cloglog.voxdez.com pointing to the tunnel
cloudflared tunnel route dns cloglog-webhooks cloglog.voxdez.com

# 5. Create config file
cat > ~/.cloudflared/config.yml << 'EOF'
tunnel: cloglog-webhooks
credentials-file: /home/sachin/.cloudflared/<TUNNEL_UUID>.json

ingress:
  - hostname: cloglog.voxdez.com
    service: http://localhost:8000
  - service: http_status:404
EOF
```

**Cloudflare setup required:** The `cloudflared tunnel route dns` command automatically creates the CNAME record in Cloudflare DNS. No manual DNS configuration needed — cloudflared handles it. The only prerequisite is that `voxdez.com` is active on Cloudflare (which it is).

**Port note:** The `service` URL must use the backend port from the worktree's `.env` file (`$BACKEND_PORT`). For the main dev environment, this is `8000`. The tunnel config should reference the stable production port, not a worktree-specific port.

#### Running the Tunnel

**Decision: Run as a systemd service for automatic restart.**

```bash
# Install as systemd service
sudo cloudflared service install

# Or run manually for debugging
cloudflared tunnel run cloglog-webhooks
```

#### GitHub App Configuration

In the GitHub App settings (https://github.com/settings/apps/cloglog-agent):

1. **Webhook URL:** `https://cloglog.voxdez.com/api/v1/webhooks/github`
2. **Webhook secret:** Same value as `GITHUB_WEBHOOK_SECRET` in `.env`
3. **Subscribe to events:** `Pull requests`, `Pull request reviews`, `Check runs`

#### When the Dev Machine is Off

GitHub does **not** auto-retry failed webhook deliveries. If the tunnel is down:
- Deliveries fail (GitHub records them as failed)
- They can be manually redelivered from the GitHub App webhook delivery log (retained for 3 days)
- For cloglog's use case (dev tool, single developer), this is acceptable. If the machine is off, no agents are running anyway.

### App Registration in app.py

```python
# In create_app(), after existing router includes:
from src.gateway.webhook import router as webhook_router
app.include_router(webhook_router, prefix="/api/v1")
```

In the `lifespan` function, register consumers:

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    from src.gateway.notification_listener import run_notification_listener
    from src.gateway.webhook_dispatcher import webhook_dispatcher
    from src.gateway.webhook_consumers import AgentNotifierConsumer
    from src.gateway.review_engine import ReviewEngineConsumer

    # Register webhook consumers
    webhook_dispatcher.register(AgentNotifierConsumer())
    if settings.review_enabled:
        webhook_dispatcher.register(ReviewEngineConsumer())

    task = asyncio.create_task(run_notification_listener())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
```

## F-36: PR Review Webhook Server

### Design Principle: Local CLI Agent, Not Cloud API

**Decision: Use a local CLI agent (OpenAI Codex) for reviews, not a cloud API.**

Rationale:
- Using a different LLM (OpenAI Codex) from the one writing the code (Claude) provides genuine diversity in review perspective — different models catch different issues
- CLI agents run locally, avoiding API costs entirely
- The agent has full filesystem access to read CLAUDE.md, DDD context map, and project rules directly — no need to stuff them into API prompts
- No token limits, chunking logic, or rate limiting needed — the CLI agent handles context management internally

### Data Flow

1. `WebhookDispatcher` delivers `PR_OPENED` or `PR_SYNCHRONIZE` event to `ReviewEngineConsumer`
2. Consumer fetches the PR diff using `gh pr diff` (via bot token)
3. Consumer writes a prompt file containing the diff and review instructions
4. Consumer launches a local Codex CLI agent as a subprocess
5. The agent reviews the diff and writes structured JSON to an output file
6. Consumer reads the result and posts a review to GitHub via the review API

### Self-Review Guard

**The review engine must NOT review its own PRs.** If a PR was created by the GitHub App bot (i.e., `event.sender` matches the bot's username), skip the review.

```python
BOT_USERNAME = "cloglog-agent[bot]"

def handles(self, event: WebhookEvent) -> bool:
    if event.sender == BOT_USERNAME:
        return False
    return event.type in (WebhookEventType.PR_OPENED, WebhookEventType.PR_SYNCHRONIZE)
```

### Local Agent Integration

**Decision: Launch Codex CLI as a subprocess with a review prompt file.**

The review engine prepares a prompt file containing the diff and project rules, then launches the Codex CLI agent. The agent writes its review to a JSON output file.

#### Prompt Design

```python
REVIEW_PROMPT_TEMPLATE = """Review this pull request diff for the cloglog project.

The project follows DDD with these bounded contexts:
- Board (src/board/) — Projects, Epics, Features, Tasks
- Agent (src/agent/) — Worktrees, Sessions
- Document (src/document/) — Append-only storage
- Gateway (src/gateway/) — API composition, auth, SSE
Each context must not import from another context's internals.

Read CLAUDE.md and docs/ddd-context-map.md for full project rules.

REVIEW CRITERIA (in priority order):
1. Correctness bugs — logic errors, off-by-one, null handling, race conditions
2. DDD boundary violations — imports crossing bounded context boundaries
3. Security issues — SQL injection, auth bypass, secret leakage, SSRF
4. Testing gaps — new code paths without test coverage
5. API contract violations — response shapes not matching OpenAPI spec
6. Linting issues likely to fail CI — type errors, missing from None
7. Style and clarity — only flag if genuinely confusing, not bikeshedding

Write your review as JSON to {output_path} matching this schema:
{{
  "verdict": "approve" | "request_changes" | "comment",
  "summary": "1-2 sentence overall assessment",
  "findings": [
    {{
      "file": "src/board/routes.py",
      "line": 42,
      "severity": "high",
      "body": "Description of the issue and suggested fix"
    }}
  ]
}}

If the diff is clean, use verdict "approve" with empty findings.

DIFF:
{diff_content}
"""
```

#### Agent Launch

```python
async def _run_review_agent(self, diff: str, pr_number: int) -> ReviewResult | None:
    """Launch local Codex CLI agent to review the diff."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "review.json"
        prompt = REVIEW_PROMPT_TEMPLATE.format(
            diff_content=diff,
            output_path=output_path,
        )
        prompt_path = Path(tmpdir) / "prompt.md"
        prompt_path.write_text(prompt)

        # Launch Codex CLI agent — uses create_subprocess_exec (safe, no shell)
        proc = await asyncio.create_subprocess_exec(
            "codex", "--prompt", str(prompt_path),
            "--approval-mode", "full-auto",
            cwd=str(Path.cwd()),  # Project root for filesystem access
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            await asyncio.wait_for(proc.wait(), timeout=300)  # 5 min timeout
        except asyncio.TimeoutError:
            proc.kill()
            logger.warning("Review agent timed out for PR #%d", pr_number)
            return None

        if not output_path.exists():
            logger.warning("Review agent produced no output for PR #%d", pr_number)
            return None

        try:
            data = json.loads(output_path.read_text())
            return ReviewResult(**data)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Review agent output unparseable for PR #%d: %s", pr_number, e)
            return None
```

**Note:** The exact Codex CLI invocation will need to be validated during implementation. The agent needs:
- Read access to the project directory (for CLAUDE.md, DDD context map)
- Write access to the output JSON file
- No network access needed (runs locally)
- Auto-approval mode so it completes without human interaction

#### Structured Output Schema

```python
from pydantic import BaseModel, field_validator

class ReviewFinding(BaseModel):
    file: str
    line: int
    severity: str  # critical, high, medium, low, info
    body: str

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        allowed = {"critical", "high", "medium", "low", "info"}
        if v not in allowed:
            raise ValueError(f"severity must be one of {allowed}")
        return v

class ReviewResult(BaseModel):
    verdict: str   # approve, request_changes, comment
    summary: str
    findings: list[ReviewFinding]

    @field_validator("verdict")
    @classmethod
    def validate_verdict(cls, v: str) -> str:
        allowed = {"approve", "request_changes", "comment"}
        if v not in allowed:
            raise ValueError(f"verdict must be one of {allowed}")
        return v
```

### Rate Limiting

- Simple in-memory rate limiter: max 10 reviews per hour. If exceeded, skip and log.
- Only one review agent runs at a time (sequential via asyncio.Lock) to avoid overloading the machine.

```python
import time

class RateLimiter:
    def __init__(self, max_per_hour: int = 10) -> None:
        self._timestamps: list[float] = []
        self._max = max_per_hour

    def allow(self) -> bool:
        now = time.monotonic()
        self._timestamps = [t for t in self._timestamps if now - t < 3600]
        if len(self._timestamps) >= self._max:
            return False
        self._timestamps.append(now)
        return True
```

### Diff Filtering

Before passing the diff to the agent, filter out non-reviewable files:
- Skip: `*.lock`, `package-lock.json`, `*.min.js`, `*.min.css`, `generated-types.ts`, `*.pyc`, `*.map`
- Skip: `.env`, `.env.*`, `*.pem`, `*.key`, `credentials/`
- If the filtered diff exceeds 200K characters, post a comment saying the PR is too large for automated review

### GitHub Review API Integration

**Decision: Post as a proper GitHub review with inline comments, not issue comments.**

```python
import httpx

async def post_review(
    repo: str,
    pr_number: int,
    result: ReviewResult,
    bot_token: str,
) -> None:
    """Post a GitHub PR review with inline comments."""
    event_map = {
        "approve": "APPROVE",
        "request_changes": "REQUEST_CHANGES",
        "comment": "COMMENT",
    }
    event = event_map.get(result.verdict, "COMMENT")

    comments = []
    for finding in result.findings:
        comments.append({
            "path": finding.file,
            "line": finding.line,
            "body": f"**[{finding.severity.upper()}]** {finding.body}",
        })

    body = {
        "event": event,
        "body": f"## Automated Review (Codex)\n\n{result.summary}",
        "comments": comments,
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews",
            headers={
                "Authorization": f"Bearer {bot_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json=body,
        )
        resp.raise_for_status()
```

**GitHub review comments require `side` and `line` on the diff hunk, not the file line number.** The review engine must map agent-reported line numbers to diff hunk positions. Lines that can't be mapped become general comments in the review body.

**Bot token acquisition:** Reuse the existing `scripts/gh-app-token.py` mechanism. Extract into an importable async function:

```python
# src/gateway/github_token.py

import time
from pathlib import Path

import httpx
import jwt

APP_ID = "3235173"
INSTALLATION_ID = "120404294"
PEM_PATH = Path.home() / ".agent-vm" / "credentials" / "github-app.pem"

_cached_token: str | None = None
_cached_at: float = 0
_CACHE_TTL = 3000  # 50 minutes


async def get_github_app_token() -> str:
    """Generate a short-lived GitHub App installation token.

    Tokens are cached for 50 minutes (they expire after 60).
    """
    global _cached_token, _cached_at

    now = time.monotonic()
    if _cached_token and (now - _cached_at) < _CACHE_TTL:
        return _cached_token

    private_key = PEM_PATH.read_bytes()
    now_ts = int(time.time())
    payload = {"iat": now_ts - 60, "exp": now_ts + 600, "iss": APP_ID}
    encoded = jwt.encode(payload, private_key, algorithm="RS256")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://api.github.com/app/installations/{INSTALLATION_ID}/access_tokens",
            headers={
                "Authorization": f"Bearer {encoded}",
                "Accept": "application/vnd.github+json",
            },
            json={
                "permissions": {
                    "contents": "write",
                    "pull_requests": "write",
                    "issues": "write",
                    "workflows": "write",
                },
            },
        )
        resp.raise_for_status()
        _cached_token = resp.json()["token"]
        _cached_at = now
        return _cached_token
```

### Error Handling

| Failure | Behavior |
|---|---|
| Agent process timeout (>5 min) | Kill process, log warning, skip review. Next `synchronize` triggers retry. |
| Agent produces no output file | Log warning, skip review. |
| Agent output unparseable | Log the raw content, post a comment: "Automated review failed to parse results." |
| GitHub API error posting review | Log error. Retry once after 5 seconds. If still failing, drop it. |
| PR diff too large (>200K chars) | Post a comment: "PR too large for automated review." |
| Rate limit exceeded | Skip silently with a log warning. |
| Bot token generation fails | Log error, skip review. |
| Codex CLI not installed | Log error at startup. Disable review engine. |

### Consumer Implementation

```python
# src/gateway/review_engine.py

import asyncio
import json
import logging
import tempfile
from pathlib import Path

from src.gateway.webhook_dispatcher import WebhookConsumer, WebhookEvent, WebhookEventType

logger = logging.getLogger(__name__)

BOT_USERNAME = "cloglog-agent[bot]"


class ReviewEngineConsumer:
    """Webhook consumer that launches a local Codex agent for PR reviews."""

    def __init__(self) -> None:
        self._rate_limiter = RateLimiter(max_per_hour=settings.review_max_per_hour)
        self._review_lock = asyncio.Lock()  # One review at a time

    def handles(self, event: WebhookEvent) -> bool:
        if event.sender == BOT_USERNAME:
            return False
        return event.type in (WebhookEventType.PR_OPENED, WebhookEventType.PR_SYNCHRONIZE)

    async def handle(self, event: WebhookEvent) -> None:
        if not self._rate_limiter.allow():
            logger.warning("Review rate limit exceeded, skipping PR #%d", event.pr_number)
            return

        async with self._review_lock:
            try:
                token = await get_github_app_token()
                diff = await self._fetch_pr_diff(event.repo_full_name, event.pr_number, token)
                diff = self._filter_diff(diff)

                if len(diff) > 200_000:
                    await self._post_too_large_comment(event, token)
                    return

                result = await self._run_review_agent(diff, event.pr_number)
                if result is None:
                    return

                await post_review(event.repo_full_name, event.pr_number, result, token)

            except Exception:
                logger.exception("Review failed for PR #%d", event.pr_number)
```

## F-46: Agent PR Event Notifications

### Data Flow

1. `WebhookDispatcher` delivers PR event to `AgentNotifierConsumer`
2. Consumer resolves which agent owns this PR:
   - Extract PR URL from the event
   - Query the database: find tasks where `pr_url` matches the event's `pr_url`
   - From the task, get `worktree_id`
   - From the worktree, get the inbox path (`/tmp/cloglog-inbox-{worktree_id}`)
3. Append a structured JSON message to the agent's inbox file
4. The agent's Claude Code Monitor picks it up instantly (sub-second latency)

### Event-to-Agent Resolution

**Decision: Resolve via `Task.pr_url` -> `Task.worktree_id` -> inbox file path.**

This is the natural resolution path because:
- Tasks already store `pr_url` (set when moving to review) — `src/board/models.py:112`
- Tasks already store `worktree_id` (set when the agent starts the task) — `src/board/models.py:115`
- The inbox file pattern `/tmp/cloglog-inbox-{worktree_id}` is already established — `src/agent/services.py:87`

```python
async def resolve_agent_for_pr(pr_url: str, session: AsyncSession) -> tuple[UUID, UUID] | None:
    """Find the worktree and task for a given PR URL.

    Returns (worktree_id, task_id) or None if no match.
    """
    from src.board.repository import BoardRepository
    repo = BoardRepository(session)
    task = await repo.find_task_by_pr_url(pr_url)
    if task is None or task.worktree_id is None:
        return None
    return (task.worktree_id, task.id)
```

This requires adding a `find_task_by_pr_url` method to `BoardRepository`:

```python
async def find_task_by_pr_url(self, pr_url: str) -> Task | None:
    """Find a task by its PR URL. Returns the most recently updated match."""
    from sqlalchemy import select
    stmt = (
        select(Task)
        .where(Task.pr_url == pr_url)
        .where(Task.status.in_(["in_progress", "review"]))
        .order_by(Task.updated_at.desc())
        .limit(1)
    )
    result = await self._session.execute(stmt)
    return result.scalar_one_or_none()
```

**Branch-based fallback:** If no task has a matching `pr_url` (e.g., the PR was just opened and the agent hasn't set `pr_url` yet), fall back to branch name matching:

```python
async def resolve_agent_for_branch(
    branch_name: str, repo_full_name: str, session: AsyncSession
) -> UUID | None:
    """Find worktree by branch name as fallback.

    Matches repo_full_name against Project.repo_url (which stores the full GitHub URL)
    by checking if repo_url ends with the repo_full_name.
    """
    from src.board.repository import BoardRepository
    repo = BoardRepository(session)
    project = await repo.find_project_by_repo(repo_full_name)
    if project is None:
        return None
    from src.agent.repository import AgentRepository
    agent_repo = AgentRepository(session)
    worktree = await agent_repo.get_worktree_by_branch(project.id, branch_name)
    if worktree is not None:
        return worktree.id
    return None
```

This requires adding `get_worktree_by_branch` to `AgentRepository`:

```python
async def get_worktree_by_branch(self, project_id: UUID, branch_name: str) -> Worktree | None:
    stmt = (
        select(Worktree)
        .where(Worktree.project_id == project_id)
        .where(Worktree.branch_name == branch_name)
        .where(Worktree.status == "online")
    )
    result = await self._session.execute(stmt)
    return result.scalar_one_or_none()
```

And `find_project_by_repo` to `BoardRepository`:

```python
async def find_project_by_repo(self, repo_full_name: str) -> Project | None:
    """Find a project by GitHub repo.

    Project.repo_url stores the full URL (e.g. 'https://github.com/sachinkundu/cloglog').
    This method matches against the trailing repo_full_name (e.g. 'sachinkundu/cloglog').
    """
    stmt = (
        select(Project)
        .where(Project.repo_url.endswith(repo_full_name))
        .limit(1)
    )
    result = await self._session.execute(stmt)
    return result.scalar_one_or_none()
```

**Note:** SQLAlchemy's `String.endswith()` translates to `LIKE '%sachinkundu/cloglog'`. At cloglog's scale (single-digit projects), this is fine. If needed later, add an indexed `repo_full_name` column.

### Integration with Existing Inbox Mechanism

The agent inbox file mechanism is already used for shutdown notifications (`src/agent/services.py:87`). F-46 uses the exact same mechanism with different message types.

**Critical difference from shutdown:** Shutdown uses `write_text` (overwrite) because there's only ever one shutdown message. Webhook events can arrive in rapid succession (e.g., CI check completes + review submitted within seconds). **The webhook consumer must append, not overwrite:**

```python
# CORRECT — append mode prevents data loss
with inbox_path.open("a") as f:
    f.write(json.dumps(message) + "\n")

# WRONG — write_text overwrites, losing earlier events
# inbox_path.write_text(json.dumps(message) + "\n")
```

The Monitor tool watches for file modifications. Each append triggers a modification event. The agent reads new content from the file and acts on it.

**Message format (one JSON object per line, appended):**

```json
{"type": "pr_merged", "pr_url": "https://github.com/.../pull/123", "pr_number": 123, "task_id": "uuid", "message": "PR #123 has been MERGED. ..."}
```

```json
{"type": "review_submitted", "pr_url": "...", "pr_number": 123, "review_state": "changes_requested", "reviewer": "sachinkundu", "body": "First 500 chars of review body...", "message": "Review on PR #123: ..."}
```

```json
{"type": "ci_failed", "pr_url": "...", "pr_number": 123, "check_name": "quality", "conclusion": "failure", "message": "CI check 'quality' failure on PR #123. ..."}
```

### Consumer Implementation

```python
# src/gateway/webhook_consumers.py

import json
import logging
from pathlib import Path
from uuid import UUID

from src.gateway.webhook_dispatcher import WebhookConsumer, WebhookEvent, WebhookEventType
from src.shared.database import async_session_factory

logger = logging.getLogger(__name__)


class AgentNotifierConsumer:
    """Route PR events to the owning worktree agent via inbox file."""

    _handled = {
        WebhookEventType.PR_MERGED,
        WebhookEventType.PR_CLOSED,
        WebhookEventType.PR_OPENED,
        WebhookEventType.PR_SYNCHRONIZE,
        WebhookEventType.REVIEW_SUBMITTED,
        WebhookEventType.CHECK_RUN_COMPLETED,
    }

    def handles(self, event: WebhookEvent) -> bool:
        return event.type in self._handled

    async def handle(self, event: WebhookEvent) -> None:
        async with async_session_factory() as session:
            # Resolve which agent owns this PR
            worktree_id = await self._resolve_agent(event, session)
            if worktree_id is None:
                logger.debug("No agent found for PR %s", event.pr_url)
                return

            # Build message based on event type
            message = self._build_message(event)
            if message is None:
                return

            # Append to agent inbox (not write_text — multiple events can arrive quickly)
            inbox_path = Path(f"/tmp/cloglog-inbox-{worktree_id}")
            with inbox_path.open("a") as f:
                f.write(json.dumps(message) + "\n")
            logger.info(
                "Notified agent %s of %s on PR #%d",
                worktree_id, event.type, event.pr_number,
            )

            # For PR_MERGED, also update the task's pr_merged flag
            if event.type == WebhookEventType.PR_MERGED:
                from src.board.repository import BoardRepository
                repo = BoardRepository(session)
                task = await repo.find_task_by_pr_url(event.pr_url)
                if task is not None:
                    await repo.update_task(task.id, pr_merged=True)
                    await session.commit()

    async def _resolve_agent(self, event: WebhookEvent, session) -> UUID | None:
        """Resolve PR event to owning worktree ID.

        Primary: match Task.pr_url.
        Fallback: match Worktree.branch_name (for PRs opened before agent sets pr_url).
        """
        from src.board.repository import BoardRepository
        repo = BoardRepository(session)

        # Primary: match by pr_url
        task = await repo.find_task_by_pr_url(event.pr_url)
        if task is not None and task.worktree_id is not None:
            return task.worktree_id

        # Fallback: match by branch name
        from src.agent.repository import AgentRepository
        agent_repo = AgentRepository(session)
        project = await repo.find_project_by_repo(event.repo_full_name)
        if project is None:
            return None
        worktree = await agent_repo.get_worktree_by_branch(project.id, event.head_branch)
        if worktree is not None:
            return worktree.id

        return None

    def _build_message(self, event: WebhookEvent) -> dict | None:
        if event.type == WebhookEventType.PR_MERGED:
            return {
                "type": "pr_merged",
                "pr_url": event.pr_url,
                "pr_number": event.pr_number,
                "message": (
                    f"PR #{event.pr_number} has been MERGED. "
                    "Run the per-task shutdown sequence: "
                    "(1) emit pr_merged_notification to the main inbox, "
                    "(2) call mark_pr_merged, "
                    "(3) for spec/plan tasks call report_artifact, "
                    "(4) write shutdown-artifacts/work-log-T-<NNN>.md, "
                    "(5) build aggregate shutdown-artifacts/work-log.md, "
                    "(6) emit agent_unregistered with reason='pr_merged', "
                    "(7) call unregister_agent and exit. "
                    "Do NOT call get_my_tasks or start the next task — "
                    "the supervisor handles relaunching."
                ),
            }
        if event.type == WebhookEventType.PR_CLOSED:
            return {
                "type": "pr_closed",
                "pr_url": event.pr_url,
                "pr_number": event.pr_number,
                "message": f"PR #{event.pr_number} was closed without merging.",
            }
        if event.type == WebhookEventType.REVIEW_SUBMITTED:
            review = event.raw.get("review", {})
            state = review.get("state", "")
            body = (review.get("body") or "")[:500]
            return {
                "type": "review_submitted",
                "pr_url": event.pr_url,
                "pr_number": event.pr_number,
                "review_state": state,
                "reviewer": event.sender,
                "body": body,
                "message": (
                    f"Review on PR #{event.pr_number}: {state} by {event.sender}. "
                    + (f"Feedback: {body}" if body else "No comment body.")
                    + (" Address the feedback, push a fix, and move back to review."
                       if state == "changes_requested" else "")
                ),
            }
        if event.type == WebhookEventType.CHECK_RUN_COMPLETED:
            check = event.raw.get("check_run", {})
            conclusion = check.get("conclusion", "")
            name = check.get("name", "")
            if conclusion == "success":
                return None  # Don't notify on success — only failures matter
            return {
                "type": "ci_failed",
                "pr_url": event.pr_url,
                "pr_number": event.pr_number,
                "check_name": name,
                "conclusion": conclusion,
                "message": (
                    f"CI check '{name}' {conclusion} on PR #{event.pr_number}. "
                    "Use the github-bot skill to read the failed logs and push a fix."
                ),
            }
        # PR_OPENED and PR_SYNCHRONIZE don't need agent notification
        # (the agent already knows it pushed code)
        return None
```

### Handling Offline Agents

**Decision: Drop the notification if the agent is offline. No queuing.**

Rationale:
- If an agent is offline, nobody is reading the inbox file
- When the agent comes back online (re-registers), it will pick up its tasks and check PR state as part of its startup flow
- The inbox file is a tmpfs path that may not survive reboots anyway
- Adding a persistent notification queue adds complexity for a rare edge case (webhook arrives in the brief window between agent crash and re-registration)

**One exception: PR_MERGED events update `Task.pr_merged` in the database regardless of agent online status.** This ensures the board state is correct even if the agent never comes back. The `AgentNotifierConsumer.handle()` method does this (see implementation above).

### Replacing the /loop Polling

With F-46 in place, agents no longer need `/loop 5m` for PR state polling. The `update_task_status` MCP tool response currently instructs agents to set up a polling loop. This instruction should be updated to:

```
"Your PR is now tracked via webhooks. You will receive inbox notifications when:
- A review is submitted (with reviewer feedback)
- CI checks fail
- The PR is merged
No polling loop needed. Continue with other work or wait for notifications."
```

The MCP server's `update_task_status` tool response text needs to be updated to remove the `/loop` instruction and replace it with the webhook notification message.

## Cross-Cutting Concerns

### Security

1. **HMAC-SHA256 validation is mandatory and fail-closed.** Every webhook request must pass signature validation. If `GITHUB_WEBHOOK_SECRET` is empty, `verify_signature()` returns `False` and all requests are rejected.

2. **Webhook endpoint bypasses API access control middleware** because it uses HMAC authentication, not Bearer tokens. The bypass uses `path.startswith("/api/v1/webhooks/")` to allow future webhook endpoints.

3. **Review engine security:**
   - Diffs are treated as untrusted input in the review prompt (explicit instruction)
   - `.env`, credential files, PEM keys, and `.claude/` memory files are filtered from the diff before review
   - The bot token is generated fresh per operation (cached for 50 min) and scoped to minimum permissions
   - The Codex agent runs locally with filesystem access but no network — it cannot exfiltrate data
   - Review engine never executes code from the diff
   - Self-review guard prevents feedback loops
   - Codex agent runs as subprocess with no shell injection risk (uses `create_subprocess_exec`)

4. **No webhook secret in code.** The secret is exclusively in `.env` / environment variables. The `Settings` model reads it from the environment.

5. **Project rules sent to Claude are read-only architectural rules,** not memory files or credential paths.

### Reliability and Idempotency

1. **Idempotency via `X-GitHub-Delivery` header.** The dispatcher maintains an `OrderedDict` of seen delivery IDs (preserving insertion order for proper eviction) and skips duplicates. Cap at 10,000 entries with FIFO eviction.

2. **GitHub does not auto-retry.** Failed deliveries are recorded in GitHub's log and can be manually redelivered within 3 days. This means we do not need to handle exponential backoff or retry storms.

3. **Consumer failures are isolated.** Each consumer runs in its own `asyncio.create_task`. If the review engine fails, the agent notifier still runs, and vice versa.

4. **The webhook endpoint always returns 200** (after signature validation). Consumer processing is async. This ensures GitHub never sees a timeout.

5. **PR_MERGED writes to database** regardless of agent status, ensuring board state consistency.

6. **Inbox append is atomic at the OS level** for small writes (under PIPE_BUF, typically 4096 bytes). Webhook messages are well under this limit, so concurrent appends from multiple async tasks won't interleave.

### Testing Strategy

#### Unit Tests (pytest)

1. **HMAC validation:** Test `verify_signature()` with valid/invalid/empty signatures and empty secret. Use a known secret and pre-computed HMAC.

2. **Event parsing:** Test `parse_webhook_event()` with fixture JSON payloads for each event type. Verify correct `WebhookEvent` construction. Test edge cases: unknown action types return None, `pull_request_review` with `edited` action returns None, `check_run` with `created` action returns None.

3. **Dispatcher:** Test that `WebhookDispatcher` calls the right consumers, skips duplicates, handles `OrderedDict` eviction correctly, and isolates consumer failures.

4. **Agent resolution:** Test `resolve_agent_for_pr()` with: matching pr_url, no match, branch fallback, offline agent.

5. **Review engine prompt construction:** Test that large diffs are chunked correctly, sensitive files are excluded, and the prompt fits within token limits.

6. **Self-review guard:** Test that PRs from `cloglog-agent[bot]` are skipped.

#### Fixture Data

Create `tests/fixtures/webhooks/` with JSON files:
- `pr_opened.json` — real GitHub `pull_request` payload (sanitized)
- `pr_synchronize.json`
- `pr_closed_merged.json`
- `pr_closed_not_merged.json`
- `review_submitted_approved.json`
- `review_submitted_changes_requested.json`
- `review_edited.json` — should be ignored
- `check_run_completed_failure.json`
- `check_run_created.json` — should be ignored

Capture these from the GitHub webhook delivery log for cloglog's own PRs.

#### Integration Tests

1. **Webhook endpoint:** POST to `/api/v1/webhooks/github` with a valid HMAC signature and a fixture payload. Verify 200 response and that the dispatcher was called.

2. **Agent notification flow:** Create a project, worktree, and task with a pr_url. Send a PR_MERGED webhook. Verify the inbox file was written (appended) and `Task.pr_merged` was updated.

3. **Review engine (mock Claude):** Mock the Anthropic API client to return a canned review result. Verify the GitHub review API is called with correct parameters.

4. **Middleware bypass:** Verify that the webhook endpoint is accessible without Bearer token or dashboard key.

#### E2E Test

1. Create a test branch and PR using the GitHub API (bot token)
2. Verify the webhook is received and a review is posted
3. Merge the PR, verify the agent notification is written

This E2E test requires the tunnel to be running and should be tagged as `@pytest.mark.e2e` to exclude from regular test runs.

### Configuration and Environment

New environment variables:

| Variable | Description | Required | Default |
|---|---|---|---|
| `GITHUB_WEBHOOK_SECRET` | HMAC secret for webhook validation | Yes (prod) | `""` (empty = reject all) |
| `REVIEW_AGENT_CMD` | CLI command to launch review agent | No | `codex` |
| `REVIEW_MAX_PER_HOUR` | Rate limit for reviews | No | `10` |
| `REVIEW_ENABLED` | Enable/disable automated reviews | No | `true` |

Add these to `src/shared/config.py`:

```python
class Settings(BaseSettings):
    # ... existing ...
    github_webhook_secret: str = ""
    review_agent_cmd: str = "codex"
    review_max_per_hour: int = 10
    review_enabled: bool = True
```

### New Python Dependencies

- `PyJWT[crypto]` — JWT generation for GitHub App tokens (already used by `scripts/gh-app-token.py` via `uv run --with`, but now needed as a project dependency for `src/gateway/github_token.py`)
- `httpx` — already a project dependency (`pyproject.toml`)

### External Dependencies (not Python packages)

- `codex` (OpenAI Codex CLI) — must be installed and available on PATH for F-36 review engine. If not installed, the review engine is disabled at startup.

## Implementation Plan

### Phase 1: F-47 — Webhook Ingestion Infrastructure

**Scope:** Receive webhooks, validate, parse, dispatch. No consumers yet (dispatcher has zero consumers, which is fine — events just get logged).

**Tasks:**

1. **T-1: Webhook endpoint and HMAC validation**
   - Create `src/gateway/webhook.py` with the `POST /webhooks/github` route
   - Add `verify_signature()` function (fail-closed when secret is empty)
   - Add `github_webhook_secret` to Settings
   - Add middleware bypass for `/api/v1/webhooks/` prefix
   - Register route in `app.py`
   - Tests: HMAC validation unit tests (valid, invalid, empty signature, empty secret), endpoint integration test with fixture payloads, middleware bypass integration test

2. **T-2: Event parser and dispatcher**
   - Create `src/gateway/webhook_dispatcher.py` with `WebhookEvent`, `WebhookEventType`, `WebhookDispatcher` (using `OrderedDict` for idempotency)
   - Implement `parse_webhook_event()` for all event types including action filtering (`pull_request_review` only on `submitted`, `check_run` only on `completed`)
   - Create `tests/fixtures/webhooks/` with fixture JSON payloads
   - Tests: Parsing unit tests for each event type and ignored actions, dispatcher fan-out test, idempotency test, OrderedDict eviction test

3. **T-3: Cloudflared tunnel setup**
   - Install and configure cloudflared on the dev machine
   - Create named tunnel, configure DNS
   - Configure GitHub App webhook URL and secret
   - Verify end-to-end: push a test commit, confirm webhook arrives
   - This is an infrastructure task, not a code task

### Phase 2: F-36 + F-46 (parallel, independent consumers)

#### F-36: PR Review Engine

4. **T-4: GitHub API client module**
   - Create `src/gateway/github_token.py` — extract token generation from `scripts/gh-app-token.py` into an async function with 50-minute caching
   - Add `PyJWT[crypto]` as a project dependency
   - Add review config fields to Settings
   - Tests: Token caching test, token refresh test

5. **T-5: Codex review engine**
   - Create `src/gateway/review_engine.py` with `ReviewEngineConsumer`
   - Implement diff filtering, prompt file generation, Codex CLI subprocess launch, result parsing
   - Implement self-review guard (skip bot PRs)
   - Implement rate limiting and sequential lock
   - Check for Codex CLI availability at startup
   - Register consumer in `lifespan` (conditional on `review_enabled` and Codex availability)
   - Tests: Diff filtering tests, self-review guard test, result parsing test, subprocess mock test

6. **T-6: GitHub review posting**
   - Implement `post_review()` with diff line mapping logic
   - Wire up the full flow: webhook -> diff fetch -> Codex agent -> post review
   - E2E test with a real PR (manual, documented in demo)
   - Tests: Diff line mapping tests, mock-based test for review posting, integration test for full flow

#### F-46: Agent PR Event Notifications

7. **T-7: Agent resolution and notification**
   - Create `src/gateway/webhook_consumers.py` with `AgentNotifierConsumer`
   - Add `find_task_by_pr_url()` to `BoardRepository`
   - Add `get_worktree_by_branch()` to `AgentRepository`
   - Add `find_project_by_repo()` to `BoardRepository` (matching `repo_full_name` against `Project.repo_url` suffix)
   - Register consumer in `lifespan`
   - **Use `open("a")` for inbox writes, not `write_text`**
   - Tests: Resolution tests (pr_url match, branch fallback, no match), notification append test

8. **T-8: PR_MERGED database update**
   - In `AgentNotifierConsumer.handle()`, update `Task.pr_merged = True` when a merge event arrives
   - Verify this works even when the agent is offline (no inbox write, but DB update still happens)
   - Tests: Verify database update on merge event, verify no update on close-without-merge

9. **T-9: Remove polling loop instructions**
   - Update MCP server's `update_task_status` tool response to replace `/loop` instructions with webhook notification explanation
   - Update `plugins/cloglog/skills/github-bot/SKILL.md` to document the webhook-based flow
   - This is a documentation/config task

### Task Dependencies

```
T-1 ──> T-2 ──> T-3 (infrastructure, can run after T-1)
                 │
        ┌────────┴────────┐
        ▼                 ▼
      T-4 ──> T-5 ──> T-6   T-7 ──> T-8 ──> T-9
      (F-36 track)           (F-46 track)
```

T-4 through T-6 and T-7 through T-9 can run in parallel after T-2 is complete.

### Alembic Migration

**No new tables needed.** The only schema changes are new repository methods (`find_task_by_pr_url`, `get_worktree_by_branch`, `find_project_by_repo`) which query existing columns. No migration required.

Consider adding an index on `Task.pr_url` for faster lookup if query performance becomes an issue (it won't at current scale — dozens of tasks, not thousands). If added later:

```python
# alembic migration
op.create_index("ix_tasks_pr_url", "tasks", ["pr_url"])
```

## Open Questions

None. All decisions have been made. Key decisions summary:

1. **Gateway context** owns all webhook infrastructure
2. **In-process async pub/sub** for dispatching (no database queue)
3. **Static consumer registration** at startup
4. **No new database tables** — events are transient
5. **Per-file chunking** for large PR diffs (max 4 Claude API calls per PR)
6. **Local Codex CLI agent** for reviews (different LLM perspective, no API costs)
7. **Inbox file append** for agent notifications (existing mechanism, append mode for safety)
8. **Drop notifications for offline agents** (no persistent queue, but DB updated for PR_MERGED)
9. **Named cloudflared tunnel** with stable subdomain
10. **HMAC-SHA256** validation, fail-closed (empty secret rejects all)
11. **Self-review guard** prevents bot from reviewing its own PRs
12. **OrderedDict** for idempotency with proper FIFO eviction
13. **GitHub App token cached** for 50 minutes (expires after 60)
14. **Diff line mapping** for accurate inline review comments
15. **cloglog.voxdez.com** subdomain on existing Cloudflare domain for tunnel
