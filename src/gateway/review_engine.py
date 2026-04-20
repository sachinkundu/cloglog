"""F-36 PR review engine — Codex CLI driven code review, webhook to GitHub review.

The consumer subscribes to ``pr_opened`` and ``pr_synchronize`` webhook events,
fetches the PR diff via ``gh pr diff`` (authenticated with the GitHub App bot
token), filters lockfiles and sensitive paths, writes a prompt to a temp dir,
launches the configured review agent as a subprocess, parses a JSON
``ReviewResult`` from a known output path, and posts the review back to GitHub
via ``POST /repos/{owner}/{repo}/pulls/{pr_number}/reviews``.

Design constraints from ``docs/contracts/webhook-pipeline-spec.md`` (F-36):
- Skip self-authored PRs (``cloglog-agent[bot]``) to avoid feedback loops.
- At most one review runs at a time (``asyncio.Lock``) to bound local load.
- Rolling-hour rate limit (default 10 reviews/hour) to bound external load.
- Hard cap of 200K characters on the filtered diff — larger PRs skip review.
- 5-minute subprocess timeout; a killed agent simply skips this revision.
- Findings whose ``(file, line)`` pair isn't in the filtered diff are moved
  from inline comments to the review summary body, so a single out-of-diff
  finding never causes GitHub to reject the whole review with a 422.
- The review POST retries once after ``REVIEW_POST_RETRY_DELAY_SECONDS`` on
  HTTP failure; a second failure drops the review with a warning.
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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import httpx
from pydantic import BaseModel, field_validator

from src.gateway.review_skip_comments import SkipReason, post_skip_comment
from src.gateway.webhook_dispatcher import WebhookEvent, WebhookEventType
from src.shared.config import settings

logger = logging.getLogger(__name__)

# Both bot identities — skip review if the PR author is either bot
_CLAUDE_BOT: Final = "sakundu-claude-assistant[bot]"
_CODEX_BOT: Final = "cloglog-codex-reviewer[bot]"
_BOT_USERNAMES: Final = frozenset({_CLAUDE_BOT, _CODEX_BOT})
MAX_DIFF_CHARS: Final = 200_000
REVIEW_TIMEOUT_SECONDS: Final = 300.0
RATE_LIMIT_WINDOW_SECONDS: Final = 3600.0
REVIEW_POST_RETRY_DELAY_SECONDS: Final = 5.0
REVIEW_REQUEST_TIMEOUT_SECONDS: Final = 30.0
# Maximum number of bot reviews per PR. The cycle is at most:
#   (1) author opens PR → bot reviews → claude-coding-agent pushes a fix,
#   (2) bot reviews the fix → claude-coding-agent pushes another fix → human decides.
# A single round (one bot review, one coder fix, then human approves) is
# also fine when the first review is trivially addressable. What the cap
# prevents is a third bot review on top of two prior ones — by that point
# the human reviewer has enough context to act.
MAX_REVIEWS_PER_PR: Final = 2
# When the codex subprocess times out we kill it, then best-effort drain any
# stderr the kernel has already flushed into the pipe. 1s is enough for the
# kernel to hand over the buffered bytes without blocking the handler.
_STDERR_POSTMORTEM_READ_SECONDS: Final = 1.0
# Health probe caps — deliberately tight: these are diagnostics, not a retry
# budget. A slow probe is no better than no probe.
_HEALTH_PROBE_TIMEOUT_SECONDS: Final = 3.0
# How many trailing stderr lines to carry into logs and PR comments.
_STDERR_TAIL_LINES: Final = 30

_HUNK_HEADER_RE: Final = re.compile(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

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

_REVIEW_PROMPT_PATH: Final = Path(".github/codex/prompts/review.md")
_REVIEW_SCHEMA_PATH: Final = Path(".github/codex/review-schema.json")

# Fallback prompt when the project doesn't have .github/codex/prompts/review.md
_FALLBACK_PROMPT: Final = """\
Review this code change. Focus on correctness, security, and maintainability bugs.
Only flag issues introduced by this diff, not pre-existing problems.
If the patch is correct, say so.
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
    """Output of one review pass — the shape the agent writes to its output file."""

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

    def seconds_until_next_slot(self) -> float:
        """Seconds until the oldest timestamp ages out of the window.

        Returns ``0.0`` if a slot is currently free. Used to build the
        "retry after ~N minutes" message in the rate-limit skip comment.
        """
        now = time.monotonic()
        active = [t for t in self._timestamps if now - t < RATE_LIMIT_WINDOW_SECONDS]
        # When max_per_hour is 0 the window is always "full" but there are
        # no timestamps to wait on — the limit is effectively permanent.
        if not active or len(active) < self._max:
            return 0.0
        oldest = min(active)
        return max(0.0, (oldest + RATE_LIMIT_WINDOW_SECONDS) - now)


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


def _load_project_prompt(project_root: Path) -> str:
    """Load the review prompt from the project, or use fallback."""
    prompt_file = project_root / _REVIEW_PROMPT_PATH
    if prompt_file.exists():
        return prompt_file.read_text()
    return _FALLBACK_PROMPT


def _get_schema_path(project_root: Path) -> Path | None:
    """Return the review schema path if it exists in the project."""
    schema_file = project_root / _REVIEW_SCHEMA_PATH
    return schema_file if schema_file.exists() else None


def is_review_agent_available() -> bool:
    """Return True if the configured review agent command exists on PATH."""
    return shutil.which(settings.review_agent_cmd) is not None


def resolve_review_source_root() -> Path:
    """Resolve the filesystem root codex will read.

    Mirrors the fallback inside ``_run_review_agent`` so the startup log
    reports exactly what the review path will be at request time.
    """
    return settings.review_source_root or Path.cwd()


def log_review_source_root(logger_: logging.Logger) -> None:
    """Log the resolved review source root and its git HEAD SHA.

    Called at backend boot when the review engine is active. A mismatch
    between the reported SHA and ``origin/main`` is the exact fingerprint
    of the T-255 false-negative bug — surfacing it in the startup log
    makes future regressions obvious to whoever reads the log.

    Errors from the git probe are swallowed: a bogus or missing path must
    not block boot.
    """
    import subprocess  # local: keep top-level imports lean

    root = resolve_review_source_root()
    source = "settings.review_source_root" if settings.review_source_root else "Path.cwd() fallback"
    sha = "unknown"
    try:
        result = subprocess.run(  # noqa: S603 -- fixed argv, root is from trusted config
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            sha = result.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError) as err:
        logger_.warning("Review source root git probe failed: %s", err)
    logger_.info("Review source root: %s @ %s (%s)", root, sha, source)


def extract_diff_new_lines(diff: str) -> dict[str, set[int]]:
    """Map each changed file to the set of new-side line numbers visible in its hunks.

    GitHub's review-comment API will only accept an inline comment whose
    ``(path, line, side=RIGHT)`` combination appears inside the PR diff.
    Lines not in this map cannot be inlined — they must be appended to the
    review summary body instead.

    Context lines AND added lines are both commentable on the ``RIGHT`` side.
    Removed lines are on the ``LEFT`` side and we don't support commenting on
    them (findings come from the reviewer looking at the new revision).
    """
    result: dict[str, set[int]] = {}
    current_file: str | None = None
    current_new_line = 0
    in_hunk = False

    for line in diff.splitlines():
        if line.startswith("diff --git "):
            current_file = _extract_target_path(line)
            in_hunk = False
            continue
        if line.startswith("@@"):
            match = _HUNK_HEADER_RE.match(line)
            if match and current_file is not None:
                current_new_line = int(match.group(1))
                in_hunk = True
            else:
                in_hunk = False
            continue
        if not in_hunk or current_file is None:
            continue

        if line.startswith("+++") or line.startswith("---"):
            # Diff preamble markers — not hunk content
            continue
        if line.startswith("+"):
            result.setdefault(current_file, set()).add(current_new_line)
            current_new_line += 1
        elif line.startswith("-"):
            # Removal — doesn't consume a new-side line number
            continue
        elif line.startswith("\\"):
            # "\ No newline at end of file" — skip
            continue
        else:
            # Context line (starts with " " or empty) — commentable
            result.setdefault(current_file, set()).add(current_new_line)
            current_new_line += 1

    return result


def parse_review_output(raw: str) -> ReviewResult | None:
    """Parse the agent's JSON output; return None on any decode/validation error."""
    try:
        data = json.loads(raw)
        return ReviewResult.model_validate(data)
    except (json.JSONDecodeError, ValueError) as err:
        logger.warning("Review agent output unparseable: %s", err)
        return None


def _partition_findings(
    result: ReviewResult, valid_lines: dict[str, set[int]]
) -> tuple[list[dict[str, Any]], list[ReviewFinding]]:
    """Split findings into inline-postable comments and orphans for the body."""
    inline: list[dict[str, Any]] = []
    orphans: list[ReviewFinding] = []
    for finding in result.findings:
        allowed = valid_lines.get(finding.file, set())
        if finding.line in allowed:
            inline.append(
                {
                    "path": finding.file,
                    "line": finding.line,
                    "side": "RIGHT",
                    "body": f"**[{finding.severity.upper()}]** {finding.body}",
                }
            )
        else:
            orphans.append(finding)
    return inline, orphans


def _format_review_body(result: ReviewResult, orphans: list[ReviewFinding]) -> str:
    """Assemble the top-level review body with the summary and any orphan findings."""
    verdict_icon = {
        "approve": "pass",
        "request_changes": "warning",
        "comment": "info",
    }.get(result.verdict, "info")
    lines = [
        f":{verdict_icon}: {result.summary}",
    ]
    if orphans:
        lines += ["", "### Findings not attached to a diff line", ""]
        for f in orphans:
            lines.append(f"- **[{f.severity.upper()}]** `{f.file}:{f.line}` — {f.body}")
    return "\n".join(lines)


async def count_bot_reviews(
    repo_full_name: str,
    pr_number: int,
    token: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> int:
    """Return how many reviews the bot has already posted on this PR.

    Uses ``GET /repos/{owner}/{repo}/pulls/{pr_number}/reviews`` and counts
    entries whose ``user.login`` matches a known bot username. A network failure
    surfaces as a ``RuntimeError`` — the caller decides whether to proceed
    (for safety the consumer currently skips the review on uncertainty).
    """
    url = f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}/reviews"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    close_when_done = client is None
    http = client or httpx.AsyncClient()
    try:
        resp = await http.get(url, headers=headers, timeout=REVIEW_REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
        reviews = resp.json()
    finally:
        if close_when_done:
            await http.aclose()
    return sum(1 for r in reviews if (r.get("user") or {}).get("login") == _CODEX_BOT)


async def post_review(
    repo_full_name: str,
    pr_number: int,
    result: ReviewResult,
    diff: str,
    token: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> bool:
    """Post a GitHub PR review. Returns ``True`` on success, ``False`` on drop.

    Findings whose ``(file, line)`` pair isn't in the filtered diff are moved
    from inline comments to the summary body so GitHub never rejects the
    whole review because of one stray line number. On an HTTP failure the
    request is retried once after a short delay (per the spec); if the
    retry also fails the review is dropped with a warning.
    """
    valid_lines = extract_diff_new_lines(diff)
    inline, orphans = _partition_findings(result, valid_lines)
    # The bot never approves or requests changes — only the human reviewer
    # gates merge state. The agent's verdict is recorded in the body instead.
    payload = {
        "event": "COMMENT",
        "body": _format_review_body(result, orphans),
        "comments": inline,
    }
    url = f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}/reviews"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async def _attempt(c: httpx.AsyncClient) -> httpx.Response:
        return await c.post(
            url,
            headers=headers,
            json=payload,
            timeout=REVIEW_REQUEST_TIMEOUT_SECONDS,
        )

    close_when_done = client is None
    http = client or httpx.AsyncClient()
    try:
        try:
            resp = await _attempt(http)
            resp.raise_for_status()
            return True
        except (httpx.HTTPError, httpx.HTTPStatusError) as first_err:
            logger.warning(
                "post_review failed for PR #%d (attempt 1): %s — retrying in %.0fs",
                pr_number,
                first_err,
                REVIEW_POST_RETRY_DELAY_SECONDS,
            )
            await asyncio.sleep(REVIEW_POST_RETRY_DELAY_SECONDS)
            try:
                resp = await _attempt(http)
                resp.raise_for_status()
                return True
            except (httpx.HTTPError, httpx.HTTPStatusError) as second_err:
                logger.error(
                    "post_review failed for PR #%d after retry: %s — dropping review",
                    pr_number,
                    second_err,
                )
                return False
    finally:
        if close_when_done:
            await http.aclose()


class ReviewEngineConsumer:
    """Webhook consumer that runs a local review agent on every PR push."""

    _handled = frozenset({WebhookEventType.PR_OPENED, WebhookEventType.PR_SYNCHRONIZE})

    def __init__(self, *, max_per_hour: int | None = None) -> None:
        rate = max_per_hour if max_per_hour is not None else settings.review_max_per_hour
        self._rate_limiter = RateLimiter(max_per_hour=rate)
        self._lock = asyncio.Lock()

    def handles(self, event: WebhookEvent) -> bool:
        # Only skip if the Codex reviewer bot itself triggered the event
        # (prevents review-of-review loops). Claude bot PRs SHOULD be reviewed.
        if event.sender == _CODEX_BOT:
            return False
        return event.type in self._handled

    async def handle(self, event: WebhookEvent) -> None:
        if not self._rate_limiter.allow():
            wait_seconds = self._rate_limiter.seconds_until_next_slot()
            logger.warning(
                "Review rate limit exceeded, skipping PR #%d (%s)",
                event.pr_number,
                event.repo_full_name,
            )
            await self._notify_skip(
                event,
                SkipReason.RATE_LIMIT,
                (
                    f"Codex review skipped: rate limit exceeded "
                    f"({settings.review_max_per_hour} reviews/hour). "
                    f"Will retry after ~{int(wait_seconds // 60)} minutes."
                ),
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

    async def _notify_skip(self, event: WebhookEvent, reason: SkipReason, body: str) -> None:
        """Post a skip-notification comment on the PR as the Codex bot.

        Never raises — a token fetch failure or POST error must never cause
        the short-circuit to fail; the caller proceeds either way.
        """
        from src.gateway.github_token import get_codex_reviewer_token

        try:
            token = await get_codex_reviewer_token()
        except Exception as err:
            logger.warning(
                "Cannot fetch Codex token to post skip comment (pr=%d reason=%s): %s",
                event.pr_number,
                reason.value,
                err,
            )
            return
        try:
            await post_skip_comment(event.repo_full_name, event.pr_number, reason, body, token)
        except Exception as err:
            logger.warning(
                "Unexpected error posting skip comment (pr=%d reason=%s): %s",
                event.pr_number,
                reason.value,
                err,
            )

    async def _review_pr(self, event: WebhookEvent) -> None:
        from src.gateway.github_token import get_codex_reviewer_token, get_github_app_token

        # Claude bot token for reading diffs (has contents:read)
        claude_token = await get_github_app_token()
        # Codex reviewer bot token for posting reviews (separate identity)
        review_token = await get_codex_reviewer_token()

        prior = await count_bot_reviews(event.repo_full_name, event.pr_number, review_token)
        if prior >= MAX_REVIEWS_PER_PR:
            logger.info(
                "PR #%d already has %d bot reviews (cap=%d) — skipping",
                event.pr_number,
                prior,
                MAX_REVIEWS_PER_PR,
            )
            await self._notify_skip(
                event,
                SkipReason.MAX_REVIEWS,
                (
                    f"Codex review skipped: this PR already has the "
                    f"maximum of {MAX_REVIEWS_PER_PR} bot reviews. "
                    f"Request human review."
                ),
            )
            return

        diff = await self._fetch_pr_diff(event.repo_full_name, event.pr_number, claude_token)
        filtered = filter_diff(diff)
        if not filtered.strip():
            logger.info("PR #%d has no reviewable files after filtering", event.pr_number)
            await self._notify_skip(
                event,
                SkipReason.NO_REVIEWABLE_FILES,
                (
                    "Codex review skipped: no reviewable files after "
                    "filtering (only lockfiles / generated / excluded paths)."
                ),
            )
            return
        if len(filtered) > MAX_DIFF_CHARS:
            logger.warning(
                "PR #%d diff (%d chars) exceeds %d-char cap — skipping review",
                event.pr_number,
                len(filtered),
                MAX_DIFF_CHARS,
            )
            await self._notify_skip(
                event,
                SkipReason.DIFF_TOO_LARGE,
                (
                    f"Codex review skipped: diff too large "
                    f"({len(filtered)} chars, cap {MAX_DIFF_CHARS}). "
                    f"Break into smaller PRs or request human review."
                ),
            )
            return

        result = await self._run_review_agent(filtered, event, review_token)
        if result is None:
            # Skip comment (timeout / unparseable) already posted inside _run_review_agent.
            return

        posted = await post_review(
            event.repo_full_name, event.pr_number, result, filtered, review_token
        )
        logger.info(
            "Review %s for PR #%d: verdict=%s findings=%d",
            "posted" if posted else "dropped",
            event.pr_number,
            result.verdict,
            len(result.findings),
        )

    async def _fetch_pr_diff(self, repo_full_name: str, pr_number: int, token: str) -> str:
        """Fetch the PR diff via ``gh pr diff`` using the GitHub App bot token."""
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

    async def _run_review_agent(
        self,
        diff: str,
        event: WebhookEvent,
        codex_token: str,
    ) -> ReviewResult | None:
        """Launch ``codex exec`` with the project prompt and diff via stdin.

        On timeout: capture buffered stderr, run parallel health probes
        (``codex --version`` + ``GET api.github.com/zen``), emit a
        structured log entry, and retry once. A second consecutive timeout
        posts an ``agent_timeout`` skip comment and returns ``None``.
        On unparseable output: post an ``agent_unparseable`` skip comment
        with a short stderr excerpt and return ``None``.

        Silent failure is never acceptable here — see PR #149 / #159.
        """
        # `settings.review_source_root` must point at a checkout of the PR's
        # merge target (usually main). When unset, fall back to Path.cwd() —
        # fine for dev, wrong in prod where the backend runs out of a prod
        # checkout that trails main. See T-255.
        project_root = settings.review_source_root or Path.cwd()
        prompt = _load_project_prompt(project_root)
        schema_path = _get_schema_path(project_root)
        full_prompt = f"{prompt}\n\nDIFF:\n{diff}"

        last_outcome: _AgentAttemptOutcome | None = None
        # Matches T-229's retry philosophy: one retry swallows a transient
        # stall; a second consecutive timeout is systemic and must surface.
        for attempt in (1, 2):
            outcome = await self._run_agent_once(
                full_prompt, project_root, schema_path, event.pr_number
            )
            last_outcome = outcome
            if outcome.result is not None:
                return outcome.result
            if outcome.timed_out:
                if attempt == 1:
                    logger.info(
                        "Review agent timed out (attempt 1) for PR #%d — retrying once",
                        event.pr_number,
                    )
                    continue
                codex_alive, codex_detail = await _probe_codex_alive()
                github_reachable, github_detail = await _probe_github_reachable()
                log_entry = {
                    "event": "review_timeout",
                    "pr_number": event.pr_number,
                    "attempt": attempt,
                    "stderr_excerpt": outcome.stderr_excerpt,
                    "codex_alive": codex_alive,
                    "codex_probe": codex_detail,
                    "github_reachable": github_reachable,
                    "github_probe": github_detail,
                    "elapsed_seconds": round(outcome.elapsed_seconds, 2),
                }
                logger.warning("review_timeout %s", log_entry)
                body = _format_timeout_body(
                    outcome, codex_alive, codex_detail, github_reachable, github_detail
                )
                await self._post_agent_skip(event, SkipReason.AGENT_TIMEOUT, body, codex_token)
                return None
            # Non-timeout failure: unparseable output.
            logger.warning("Review agent produced no parseable output for PR #%d", event.pr_number)
            body = _format_unparseable_body(outcome)
            await self._post_agent_skip(event, SkipReason.AGENT_UNPARSEABLE, body, codex_token)
            return None

        # Unreachable — retained as a defensive return.
        if last_outcome is not None and last_outcome.result is not None:
            return last_outcome.result
        return None

    async def _run_agent_once(
        self,
        full_prompt: str,
        project_root: Path,
        schema_path: Path | None,
        pr_number: int,
    ) -> _AgentAttemptOutcome:
        """One invocation of the review agent — returns a typed outcome.

        On timeout: kills the subprocess and best-effort drains ``proc.stderr``
        so the caller can attach the tail to logs / PR comments.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "review.json"

            args = [
                settings.review_agent_cmd,
                "exec",
                # Host lacks CAP_NET_ADMIN, so any --sandbox mode (including
                # danger-full-access) fails in bwrap's unshare-net with
                # "loopback: Failed RTM_NEWADDR". The bypass flag skips bwrap
                # entirely. Safe here: the host IS the external sandbox.
                "--dangerously-bypass-approvals-and-sandbox",
                "--ephemeral",
                "--color",
                "never",
                "-o",
                str(output_path),
                "-C",
                str(project_root),
            ]
            if schema_path is not None:
                args += ["--output-schema", str(schema_path)]

            args.append("-")

            proc = await _create_subprocess(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(project_root),
            )
            start = time.monotonic()
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(input=full_prompt.encode()),
                    timeout=REVIEW_TIMEOUT_SECONDS,
                )
                elapsed = time.monotonic() - start
            except TimeoutError:
                elapsed = time.monotonic() - start
                captured = await _drain_stderr_after_timeout(proc)
                proc.kill()
                with contextlib.suppress(ProcessLookupError):
                    await proc.wait()
                return _AgentAttemptOutcome(
                    result=None,
                    timed_out=True,
                    stderr_excerpt=_tail_excerpt(captured),
                    elapsed_seconds=elapsed,
                )

            if proc.returncode != 0:
                logger.warning(
                    "Review agent exited %d for PR #%d: %s",
                    proc.returncode,
                    pr_number,
                    stderr.decode(errors="replace")[:500],
                )

            if output_path.exists():
                raw = output_path.read_text()
                result = self._parse_output(raw, pr_number)
                if result is not None:
                    return _AgentAttemptOutcome(
                        result=result,
                        timed_out=False,
                        returncode=proc.returncode,
                        elapsed_seconds=elapsed,
                    )

            if stdout:
                result = self._parse_output(stdout.decode(errors="replace"), pr_number)
                if result is not None:
                    return _AgentAttemptOutcome(
                        result=result,
                        timed_out=False,
                        returncode=proc.returncode,
                        elapsed_seconds=elapsed,
                    )

            return _AgentAttemptOutcome(
                result=None,
                timed_out=False,
                stderr_excerpt=_tail_excerpt(stderr),
                returncode=proc.returncode,
                elapsed_seconds=elapsed,
            )

    async def _post_agent_skip(
        self,
        event: WebhookEvent,
        reason: SkipReason,
        body: str,
        token: str,
    ) -> None:
        """Post a skip comment for an agent-path failure (timeout / unparseable).

        We already have the codex_token in hand, so we don't go through
        ``_notify_skip`` (which re-fetches). Swallows all errors — a comment
        failure must never mask the underlying agent failure.
        """
        try:
            await post_skip_comment(event.repo_full_name, event.pr_number, reason, body, token)
        except Exception as err:
            logger.warning(
                "Unexpected error posting skip comment (pr=%d reason=%s): %s",
                event.pr_number,
                reason.value,
                err,
            )

    def _parse_output(self, raw: str, pr_number: int) -> ReviewResult | None:
        """Try to parse review output, handling both schema formats.

        The Codex --output-schema format uses different field names than our
        internal ReviewResult. This method normalizes both.
        """
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Maybe there's JSON embedded in other output — try to extract it
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    data = json.loads(raw[start:end])
                except json.JSONDecodeError:
                    return None
            else:
                return None

        # Normalize from Codex schema format to our ReviewResult format
        if "overall_correctness" in data and "verdict" not in data:
            # Codex schema format — convert
            is_correct = data.get("overall_correctness") == "patch is correct"
            verdict = "approve" if is_correct else "request_changes"
            findings = []
            for f in data.get("findings", []):
                loc = f.get("code_location", {})
                line_range = loc.get("line_range", {})
                priority = f.get("priority", 0)
                severity = {3: "critical", 2: "high", 1: "medium", 0: "info"}.get(priority, "info")
                findings.append(
                    {
                        "file": loc.get("absolute_file_path", "unknown"),
                        "line": line_range.get("start", 1),
                        "severity": severity,
                        "body": f.get("body", f.get("title", "")),
                    }
                )
            data = {
                "verdict": verdict,
                "summary": data.get("overall_explanation", ""),
                "findings": findings,
            }

        return parse_review_output(json.dumps(data))


@dataclass
class _AgentAttemptOutcome:
    """Outcome of a single review-agent subprocess invocation."""

    result: ReviewResult | None
    timed_out: bool
    stderr_excerpt: str = ""
    returncode: int | None = None
    elapsed_seconds: float = 0.0


def _tail_excerpt(data: bytes | str) -> str:
    """Return the last ``_STDERR_TAIL_LINES`` of ``data`` as text.

    Used for structured logs and PR comments. Large stderr is fine —
    we only surface the tail, which is where the error usually lives.
    """
    text = data.decode(errors="replace") if isinstance(data, bytes) else data
    if not text:
        return ""
    lines = text.splitlines()
    return "\n".join(lines[-_STDERR_TAIL_LINES:])


async def _drain_stderr_after_timeout(proc: asyncio.subprocess.Process) -> bytes:
    """Best-effort read of any stderr still buffered after a timeout.

    The subprocess has not yet been killed, but ``communicate()`` is
    already cancelled — we give the kernel a short window to hand over
    whatever it had flushed. Any error short-circuits to an empty string;
    a bogus stderr is never worth failing the handler over.
    """
    if proc.stderr is None:
        return b""
    try:
        return await asyncio.wait_for(
            proc.stderr.read(),
            timeout=_STDERR_POSTMORTEM_READ_SECONDS,
        )
    except (TimeoutError, Exception):
        return b""


def _format_timeout_body(
    outcome: _AgentAttemptOutcome,
    codex_alive: bool,
    codex_detail: str,
    github_reachable: bool,
    github_detail: str,
) -> str:
    """PR comment body for a post-retry timeout."""
    lines = [
        f"Codex review failed: agent timed out after "
        f"{int(REVIEW_TIMEOUT_SECONDS)}s (retried once). "
        f"Push a new commit to retry.",
        "",
        f"- codex binary alive: **{'yes' if codex_alive else 'no'}**"
        f" ({codex_detail or 'no detail'})",
        f"- GitHub reachable: **{'yes' if github_reachable else 'no'}**"
        f" ({github_detail or 'no detail'})",
    ]
    if outcome.stderr_excerpt:
        lines += [
            "",
            "<details><summary>stderr tail</summary>",
            "",
            "```",
            outcome.stderr_excerpt,
            "```",
            "",
            "</details>",
        ]
    return "\n".join(lines)


def _format_unparseable_body(outcome: _AgentAttemptOutcome) -> str:
    """PR comment body for an unparseable-output failure."""
    rc = outcome.returncode if outcome.returncode is not None else "unknown"
    lines = [
        f"Codex review failed: agent returned an unparseable response "
        f"(exit {rc}). Push a new commit to retry.",
    ]
    if outcome.stderr_excerpt:
        lines += [
            "",
            "<details><summary>stderr tail</summary>",
            "",
            "```",
            outcome.stderr_excerpt,
            "```",
            "",
            "</details>",
        ]
    return "\n".join(lines)


async def _probe_codex_alive() -> tuple[bool, str]:
    """Check the codex binary responds to ``--version``.

    Returns ``(alive, detail)`` where ``detail`` is either the version
    string (success) or a short error marker. Never raises.
    """
    try:
        proc = await _create_subprocess(
            settings.review_agent_cmd,
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=_HEALTH_PROBE_TIMEOUT_SECONDS
        )
        if proc.returncode == 0:
            return True, stdout.decode(errors="replace").strip()[:120] or "ok"
        err = (stderr.decode(errors="replace").strip() or "nonzero exit")[:120]
        return False, err
    except TimeoutError:
        return False, f"probe timed out after {_HEALTH_PROBE_TIMEOUT_SECONDS:.0f}s"
    except OSError as err:
        return False, f"OSError: {err}"[:120]
    except Exception as err:  # noqa: BLE001 - diagnostics only, never raise
        return False, f"{type(err).__name__}: {err}"[:120]


async def _probe_github_reachable() -> tuple[bool, str]:
    """Check outbound connectivity via ``GET api.github.com/zen``.

    Returns ``(reachable, detail)``. The ``/zen`` endpoint is unauthenticated
    and always up — if it doesn't answer, outbound HTTPS is broken.
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.github.com/zen",
                timeout=_HEALTH_PROBE_TIMEOUT_SECONDS,
            )
            if resp.status_code == 200:
                return True, f"200 {resp.text.strip()[:80]}"
            return False, f"status {resp.status_code}"
    except httpx.HTTPError as err:
        return False, f"{type(err).__name__}: {err}"[:120]
    except Exception as err:  # noqa: BLE001 - diagnostics only
        return False, f"{type(err).__name__}: {err}"[:120]


async def _create_subprocess(
    *argv: str,
    stdin: int | None = None,
    stdout: int | None = None,
    stderr: int | None = None,
    cwd: str | None = None,
) -> asyncio.subprocess.Process:
    """Wrapper around ``asyncio.create_subprocess_exec`` for testability.

    Used by ``_run_review_agent`` — patch this in tests to avoid real subprocesses.
    """
    return await asyncio.create_subprocess_exec(
        *argv, stdin=stdin, stdout=stdout, stderr=stderr, cwd=cwd
    )


async def _spawn(
    *argv: str,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
) -> asyncio.subprocess.Process:
    """Thin wrapper for ``gh`` CLI calls — patch this in tests."""
    return await asyncio.create_subprocess_exec(
        *argv,
        env=env,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
