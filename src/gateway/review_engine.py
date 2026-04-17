"""F-36 PR review engine — launches a local Codex CLI agent for every new PR revision.

The consumer subscribes to ``pr_opened`` and ``pr_synchronize`` webhook events,
fetches the PR diff via ``gh pr diff`` (authenticated with the GitHub App bot
token), filters lockfiles and sensitive paths, writes a prompt to a temp dir,
launches the configured review agent as a subprocess, and parses a JSON
``ReviewResult`` from a known output path. Review posting to GitHub is handled
in T-193 — this module stops at producing a parsed ``ReviewResult``.

Design constraints from ``docs/contracts/webhook-pipeline-spec.md`` (F-36):
- Skip self-authored PRs (``cloglog-agent[bot]``) to avoid feedback loops.
- At most one review runs at a time (``asyncio.Lock``) to bound local load.
- Rolling-hour rate limit (default 10 reviews/hour) to bound external load.
- Hard cap of 200K characters on the filtered diff — larger PRs skip review.
- 5-minute subprocess timeout; a killed agent simply skips this revision.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Final

from pydantic import BaseModel, field_validator

from src.gateway.webhook_dispatcher import WebhookEvent, WebhookEventType
from src.shared.config import settings

logger = logging.getLogger(__name__)

BOT_USERNAME: Final = "cloglog-agent[bot]"
MAX_DIFF_CHARS: Final = 200_000
REVIEW_TIMEOUT_SECONDS: Final = 300.0
RATE_LIMIT_WINDOW_SECONDS: Final = 3600.0

_ALLOWED_SEVERITIES: Final = frozenset({"critical", "high", "medium", "low", "info"})
_ALLOWED_VERDICTS: Final = frozenset({"approve", "request_changes", "comment"})

# File paths we drop from the diff before sending it to the review agent.
# Lockfiles and generated artifacts add noise; secret paths must never leave the host.
_DIFF_SKIP_PATTERNS: Final = tuple(
    re.compile(pat)
    for pat in (
        r"\.lock$",
        r"(^|/)package-lock\.json$",
        r"\.min\.js$",
        r"\.min\.css$",
        r"(^|/)generated-types\.ts$",
        r"\.pyc$",
        r"\.map$",
        r"(^|/)\.env(\..*)?$",
        r"\.pem$",
        r"\.key$",
        r"(^|/)credentials/",
    )
)

REVIEW_PROMPT_TEMPLATE: Final = """\
Review this pull request diff for the cloglog project.

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
6. Linting issues likely to fail CI — type errors, missing ``from None``
7. Style and clarity — only flag if genuinely confusing, not bikeshedding

Write your review as JSON to {output_path} matching this schema:
{{
  "verdict": "approve" | "request_changes" | "comment",
  "summary": "1-2 sentence overall assessment",
  "findings": [
    {{
      "file": "src/board/routes.py",
      "line": 42,
      "severity": "critical" | "high" | "medium" | "low" | "info",
      "body": "Description of the issue and suggested fix"
    }}
  ]
}}

If the diff is clean, use verdict "approve" with an empty findings list.

DIFF:
{diff_content}
"""


class ReviewFinding(BaseModel):
    """A single inline comment the reviewer wants to leave."""

    file: str
    line: int
    severity: str
    body: str

    @field_validator("severity")
    @classmethod
    def _validate_severity(cls, v: str) -> str:
        if v not in _ALLOWED_SEVERITIES:
            raise ValueError(f"severity must be one of {sorted(_ALLOWED_SEVERITIES)}")
        return v


class ReviewResult(BaseModel):
    """Output of one review pass — posted verbatim to GitHub in T-193."""

    verdict: str
    summary: str
    findings: list[ReviewFinding]

    @field_validator("verdict")
    @classmethod
    def _validate_verdict(cls, v: str) -> str:
        if v not in _ALLOWED_VERDICTS:
            raise ValueError(f"verdict must be one of {sorted(_ALLOWED_VERDICTS)}")
        return v


class RateLimiter:
    """Rolling-window rate limiter — at most N events per hour."""

    def __init__(self, max_per_hour: int) -> None:
        self._timestamps: list[float] = []
        self._max = max_per_hour

    def allow(self) -> bool:
        now = time.monotonic()
        self._timestamps = [t for t in self._timestamps if now - t < RATE_LIMIT_WINDOW_SECONDS]
        if len(self._timestamps) >= self._max:
            return False
        self._timestamps.append(now)
        return True


def _extract_target_path(file_header_line: str) -> str | None:
    """Extract the b-side path from a ``diff --git a/<x> b/<y>`` header line."""
    marker = " b/"
    idx = file_header_line.find(marker)
    if idx == -1:
        return None
    return file_header_line[idx + len(marker) :].strip()


def _is_skippable_path(path: str) -> bool:
    return any(pat.search(path) for pat in _DIFF_SKIP_PATTERNS)


def filter_diff(diff: str) -> str:
    """Remove file sections belonging to lockfiles, generated output, or secrets.

    A unified diff is split into sections by ``diff --git`` headers. We keep a
    section only if its target path survives the skip-pattern gauntlet. Any
    leading preamble (lines before the first header) is always preserved so
    that, e.g., a plain patch without the ``diff --git`` preamble passes
    through unchanged.
    """
    if not diff:
        return diff

    sections = diff.split("\ndiff --git ")
    preamble = sections[0]
    kept: list[str] = []
    if preamble.startswith("diff --git "):
        first_line = preamble.splitlines()[0]
        first_path = _extract_target_path(first_line)
        if first_path is None or not _is_skippable_path(first_path):
            kept.append(preamble)
        preamble = ""

    for raw_section in sections[1:]:
        section = "diff --git " + raw_section
        header_line = section.splitlines()[0] if section else ""
        path = _extract_target_path(header_line)
        if path is None or not _is_skippable_path(path):
            kept.append(section)

    body = "\n".join(kept)
    if preamble and body:
        return preamble.rstrip("\n") + "\n" + body
    return body if body else preamble


def build_review_prompt(diff: str, output_path: Path) -> str:
    return REVIEW_PROMPT_TEMPLATE.format(diff_content=diff, output_path=output_path)


def is_review_agent_available() -> bool:
    """Return True if the configured review agent command exists on PATH."""
    return shutil.which(settings.review_agent_cmd) is not None


def parse_review_output(raw: str) -> ReviewResult | None:
    """Parse the agent's JSON output; return None on any decode/validation error."""
    try:
        data = json.loads(raw)
        return ReviewResult.model_validate(data)
    except (json.JSONDecodeError, ValueError) as err:
        logger.warning("Review agent output unparseable: %s", err)
        return None


class ReviewEngineConsumer:
    """Webhook consumer that runs a local review agent on every PR push."""

    _handled = frozenset({WebhookEventType.PR_OPENED, WebhookEventType.PR_SYNCHRONIZE})

    def __init__(self, *, max_per_hour: int | None = None) -> None:
        rate = max_per_hour if max_per_hour is not None else settings.review_max_per_hour
        self._rate_limiter = RateLimiter(max_per_hour=rate)
        self._lock = asyncio.Lock()

    def handles(self, event: WebhookEvent) -> bool:
        if event.sender == BOT_USERNAME:
            return False
        return event.type in self._handled

    async def handle(self, event: WebhookEvent) -> None:
        if not self._rate_limiter.allow():
            logger.warning(
                "Review rate limit exceeded, skipping PR #%d (%s)",
                event.pr_number,
                event.repo_full_name,
            )
            return

        async with self._lock:
            try:
                await self._review_pr(event)
            except Exception:
                logger.exception(
                    "Review failed for PR #%d (%s)",
                    event.pr_number,
                    event.repo_full_name,
                )

    async def _review_pr(self, event: WebhookEvent) -> None:
        diff = await self._fetch_pr_diff(event.repo_full_name, event.pr_number)
        filtered = filter_diff(diff)
        if not filtered.strip():
            logger.info("PR #%d has no reviewable files after filtering", event.pr_number)
            return
        if len(filtered) > MAX_DIFF_CHARS:
            logger.warning(
                "PR #%d diff (%d chars) exceeds %d-char cap — skipping review",
                event.pr_number,
                len(filtered),
                MAX_DIFF_CHARS,
            )
            return

        result = await self._run_review_agent(filtered, event.pr_number)
        if result is None:
            return

        # T-193 wires GitHub review posting here; for now we log so the consumer is observable.
        logger.info(
            "Review ready for PR #%d: verdict=%s findings=%d",
            event.pr_number,
            result.verdict,
            len(result.findings),
        )

    async def _fetch_pr_diff(self, repo_full_name: str, pr_number: int) -> str:
        """Fetch the PR diff via ``gh pr diff`` using the GitHub App bot token."""
        from src.gateway.github_token import get_github_app_token

        token = await get_github_app_token()
        env = os.environ.copy()
        env["GH_TOKEN"] = token
        proc = await _spawn(
            "gh",
            "pr",
            "diff",
            str(pr_number),
            "--repo",
            repo_full_name,
            env=env,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"gh pr diff failed (exit {proc.returncode}): {stderr.decode(errors='replace')}"
            )
        return stdout.decode(errors="replace")

    async def _run_review_agent(self, diff: str, pr_number: int) -> ReviewResult | None:
        """Launch the review agent CLI and parse its JSON output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            output_path = tmp / "review.json"
            prompt_path = tmp / "prompt.md"
            prompt_path.write_text(build_review_prompt(diff, output_path))

            proc = await _spawn(
                settings.review_agent_cmd,
                "--prompt",
                str(prompt_path),
                "--approval-mode",
                "full-auto",
                cwd=str(Path.cwd()),
            )
            try:
                await asyncio.wait_for(proc.wait(), timeout=REVIEW_TIMEOUT_SECONDS)
            except TimeoutError:
                proc.kill()
                with contextlib.suppress(ProcessLookupError):
                    await proc.wait()
                logger.warning("Review agent timed out for PR #%d", pr_number)
                return None

            if not output_path.exists():
                logger.warning(
                    "Review agent produced no output for PR #%d (exit=%s)",
                    pr_number,
                    proc.returncode,
                )
                return None

            return parse_review_output(output_path.read_text())


async def _spawn(
    *argv: str,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
) -> asyncio.subprocess.Process:
    """Thin wrapper around ``asyncio.create_subprocess_exec`` for testability.

    All arguments go through argv — there is no shell, so no injection vector.
    """
    return await asyncio.create_subprocess_exec(
        *argv,
        env=env,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
