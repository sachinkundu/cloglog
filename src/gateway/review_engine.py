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
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

import httpx
from pydantic import BaseModel, Field, field_validator

from src.gateway.review_skip_comments import SkipReason, post_skip_comment
from src.gateway.webhook_consumers import emit_codex_review_timed_out
from src.gateway.webhook_dispatcher import WebhookEvent, WebhookEventType
from src.shared.config import settings

if TYPE_CHECKING:
    from src.agent.interfaces import IWorktreeQuery
    from src.review.interfaces import IReviewTurnRegistry

logger = logging.getLogger(__name__)

# Bot identities in this codebase:
#  - _CLAUDE_BOT: the code-pushing bot. PRs authored by it are REVIEWED.
#  - _CODEX_BOT / _OPENCODE_BOT: reviewer bots. Their own PRs are NOT reviewed
#    (that would loop) — see ``_REVIEWER_BOTS`` usage in ``handles()`` below.
_CLAUDE_BOT: Final = "sakundu-claude-assistant[bot]"
_CODEX_BOT: Final = "cloglog-codex-reviewer[bot]"
_OPENCODE_BOT: Final = "cloglog-opencode-reviewer[bot]"
_REVIEWER_BOTS: Final = frozenset({_CODEX_BOT, _OPENCODE_BOT})
_BOT_USERNAMES: Final = frozenset({_CLAUDE_BOT, _CODEX_BOT, _OPENCODE_BOT})
MAX_DIFF_CHARS: Final = 200_000
# T-374 timeout scaling. Small diffs run fast; a 4 000-line diff genuinely
# needs longer than the historical 5-minute fixed budget to read through.
# The curve is ``base + per_line * changed_lines`` clamped to ``cap``.
# ``base`` keeps the floor at the prior fixed value (300s) so existing
# small-PR behaviour is unchanged; ``per_line`` was sized so a 1 000-line
# diff gets ~13 minutes (300 + 1000*0.5 = 800s), and ``cap`` (1800s = 30 min)
# covers the largest reviewable diff (MAX_DIFF_CHARS ≈ 4-5 k changed lines)
# without unbounding the subprocess. Document changes here when retuning.
REVIEW_TIMEOUT_BASE_SECONDS: Final = 300.0
REVIEW_TIMEOUT_PER_LINE_SECONDS: Final = 0.5
REVIEW_TIMEOUT_CAP_SECONDS: Final = 1800.0
# Historical fixed budget — retained for callers that have not yet adopted
# ``compute_review_timeout`` (e.g. the opencode loop, which has its own
# settings-driven budget). New codex paths must use ``compute_review_timeout``.
REVIEW_TIMEOUT_SECONDS: Final = REVIEW_TIMEOUT_BASE_SECONDS
RATE_LIMIT_WINDOW_SECONDS: Final = 3600.0
# T-381: extra delay added to ``seconds_until_next_slot()`` when scheduling a
# rate-limit retry. The slot ages out at ``oldest + RATE_LIMIT_WINDOW_SECONDS``;
# add a small buffer so the retry's ``allow()`` call is past the boundary even
# under monotonic-clock skew.
RATE_LIMIT_RETRY_BUFFER_SECONDS: Final = 1.0
REVIEW_POST_RETRY_DELAY_SECONDS: Final = 5.0
REVIEW_REQUEST_TIMEOUT_SECONDS: Final = 30.0
# Backstop cap on bot review sessions per PR (T-227). The primary stop
# condition is verdict-based: skip further review when the latest codex
# review emitted ``:pass:`` (verdict="approve") in its body — the bot is
# satisfied, the author has the signal. This cap is a secondary safety net
# so a coder/reviewer that never converges bails out instead of looping
# forever. 5 is chosen to give larger PRs room for a few rounds while still
# bounded; raise it only if a real PR hits the backstop without convergence.
MAX_REVIEWS_PER_PR: Final = 5
# Prefix that ``_format_review_body`` emits when ``result.verdict == "approve"``
# AND the review contains no ``critical``/``high`` findings (see the demotion
# rule in ``_format_review_body``). The cap check reads the latest codex review's
# body and treats this prefix as the approval signal on GitHub — the bot
# deliberately never posts with ``event="APPROVE"`` (see ``post_review``, which
# pins event to ``COMMENT``), so body content is the canonical approval marker.
# A contradictory approve (verdict="approve" + severe finding) is demoted to
# ``:warning:`` so this helper does not treat it as a real approval — matching
# the loop's consensus predicate (PR #201 round 2 HIGH).
_APPROVE_BODY_PREFIX: Final = ":pass:"
# When the codex subprocess times out we kill it, then best-effort drain any
# stderr the kernel has already flushed into the pipe. 1s is enough for the
# kernel to hand over the buffered bytes without blocking the handler.
_STDERR_POSTMORTEM_READ_SECONDS: Final = 1.0
# Health probe caps — deliberately tight: these are diagnostics, not a retry
# budget. A slow probe is no better than no probe.
_HEALTH_PROBE_TIMEOUT_SECONDS: Final = 3.0
# How many trailing stderr lines to carry into logs and PR comments.
_STDERR_TAIL_LINES: Final = 30
# T-281 git-subprocess deadlines. The short one covers local-only calls
# (``rev-parse``, ``worktree add``, ``worktree remove``); the longer one
# covers ``fetch`` which may need to reach origin.
_GIT_SUBPROC_TIMEOUT_SECONDS: Final = 30.0
_GIT_FETCH_TIMEOUT_SECONDS: Final = 60.0
# Where temp-dir review checkouts live inside the main clone. Relative
# to ``fallback`` (``settings.review_source_root or Path.cwd()``) because
# that is always a real git repo on this host — the place ``git worktree
# add --detach`` runs from and the place cleanup points back at.
_REVIEW_CHECKOUT_SUBDIR: Final = Path(".cloglog") / "review-checkouts"

_HUNK_HEADER_RE: Final = re.compile(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

_ALLOWED_SEVERITIES: Final = frozenset({"critical", "high", "medium", "low", "info"})
_ALLOWED_VERDICTS: Final = frozenset({"approve", "request_changes", "comment"})
_ALLOWED_STATUSES: Final = frozenset({"no_further_concerns", "review_in_progress"})

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
        # T-275: ONLY the showboat-rendered ``demo.md`` under ``docs/demos/`` is
        # noise — it is byte-exact captured output, not code. The sibling
        # ``demo-script.sh`` + ``proof_*.py`` / ``probe.py`` files under the
        # same tree ARE executed by ``scripts/run-demo.sh`` and re-run by
        # ``scripts/check-demo.sh`` on every ``make quality``, so they MUST
        # still reach codex. A broader ``docs/demos/`` regex (the shape
        # shipped in PR #197 round 1) was flagged HIGH — it hid real code
        # from review.
        r"(^|/)docs/demos/.*/demo\.md$",
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
    # Optional — used by ReviewLoop's consensus predicate (b) to key a stable
    # de-dup tuple ``(file, line, title_lower)`` across turns (spec §1.1).
    # Codex schema stores it as ``findings[].title``; the internal path populates
    # it during normalization in ``_parse_output``.
    title: str = ""

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
    # Optional top-level consensus flag (spec §1.1 predicate a). Absent or None
    # means "not yet consensus"; ``no_further_concerns`` short-circuits the
    # per-reviewer loop before its max-turn cap.
    status: str | None = None
    # T-367: optional learnings array codex emits about the *codebase* (not the
    # diff). Persisted by ReviewLoop after a successful turn and replayed into
    # the next turn's prompt as a primer so codex doesn't re-derive the same
    # architectural facts on every push. Empty list = "nothing notable learned
    # this turn"; opencode never emits learnings.
    learnings: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("verdict")
    @classmethod
    def _validate_verdict(cls, v: str) -> str:
        if v not in _ALLOWED_VERDICTS:
            raise ValueError(f"verdict must be one of {sorted(_ALLOWED_VERDICTS)}")
        return v

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v not in _ALLOWED_STATUSES:
            raise ValueError(f"status must be one of {sorted(_ALLOWED_STATUSES)}")
        return v


class RateLimiter:
    """Rolling-window rate limiter — at most N events per hour.

    T-381 reservations: a slot promised to a deferred retry is reserved
    against the window so unrelated events can't claim it before the retry
    fires. Each reservation is assigned its own concrete future wake time
    in queue order — ``reserve()`` returns that wake time, and the retry
    sleeps until then. Without per-reservation slot assignment, multiple
    same-batch retries would all compute the same ``seconds_until_next_slot``
    and fire together, busting the at-most-N-per-hour contract for
    ``max_per_hour > 1`` (codex round 4 finding).
    """

    def __init__(self, max_per_hour: int) -> None:
        self._timestamps: list[float] = []
        # T-381: wake times of scheduled retries, monotonic-clock absolute.
        self._reservations: list[float] = []
        self._max = max_per_hour

    def allow(self) -> bool:
        now = time.monotonic()
        self._timestamps = [t for t in self._timestamps if now - t < RATE_LIMIT_WINDOW_SECONDS]
        if len(self._timestamps) + len(self._reservations) >= self._max:
            return False
        self._timestamps.append(now)
        return True

    def can_reserve(self) -> bool:
        """Cap reservations at ``max_per_hour`` (T-381).

        Independent of active-timestamp count: each reservation gets its
        own slot in the queue (see ``reserve()``), so the cap only bounds
        how far into the future we'll defer a retry. Without this cap,
        every rate-limited PR added a reservation indefinitely.
        """
        return len(self._reservations) < self._max

    def reserve(self) -> float:
        """Reserve a future slot, return its monotonic wake time (T-381).

        Each reservation is placed in the queue at the earliest wake time
        that keeps the rolling-window cap intact. With ``max_per_hour=2``
        and active timestamps at T=0, T=3599, the first reservation wakes
        at T=3600 (when T=0 ages out); the second wakes at T=7199 (when
        T=3599 ages out). A naive "every retry uses ``seconds_until_next_slot``"
        scheme would wake both at ~T=3600 and run three reviews in the same
        rolling hour.

        Caller must check ``can_reserve()`` first — over-reserving silently
        admits more reviews than ``max_per_hour`` allows once the queue
        completes.
        """
        now = time.monotonic()
        active = [t for t in self._timestamps if now - t < RATE_LIMIT_WINDOW_SECONDS]
        # Combined queue of all scheduled review starts (active + reservations).
        scheduled = sorted(active + self._reservations)
        new_index = len(scheduled)
        if new_index < self._max:
            wake = now
        else:
            # Wait for the (new_index - max)-th oldest review's window
            # to roll, freeing the Nth slot.
            wake = scheduled[new_index - self._max] + RATE_LIMIT_WINDOW_SECONDS
        # Don't go backwards: clock skew or already-aged-out scheduled
        # entries could produce wake < now.
        wake = max(wake, now)
        self._reservations.append(wake)
        return wake

    def release_reservation(self, wake: float) -> None:
        """Cancel a reservation without consuming the slot (T-381)."""
        # ValueError when already released or never recorded — defensive no-op.
        with contextlib.suppress(ValueError):
            self._reservations.remove(wake)

    def consume_reservation(self, wake: float) -> None:
        """Promote a reservation to a real timestamp (T-381 retry firing).

        Atomic w.r.t. the asyncio event loop — no await between the two
        mutations — so a concurrent ``allow()`` cannot observe a momentary
        free slot.
        """
        self.release_reservation(wake)
        self._timestamps.append(time.monotonic())

    def is_permanently_blocked(self) -> bool:
        """``max_per_hour=0`` is the documented permanent-block mode.

        Distinct from ``seconds_until_next_slot() == 0.0``, which can also
        mean "a slot just aged out a millisecond ago". Use this method to
        decide whether to schedule a retry — never a numeric comparison.
        """
        return self._max == 0

    def seconds_until_next_slot(self) -> float:
        """Seconds until the oldest timestamp ages out of the window.

        Returns ``0.0`` if a slot is currently free OR if the limiter is
        permanently blocked. Callers must use ``is_permanently_blocked()``
        to disambiguate — never treat ``0.0`` as a sentinel. Note that
        T-381's retry scheduling uses ``reserve()``'s queue-aware wake
        time, not this single shared value.
        """
        now = time.monotonic()
        active = [t for t in self._timestamps if now - t < RATE_LIMIT_WINDOW_SECONDS]
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


def count_changed_lines(diff: str) -> int:
    """Count added/removed lines in a unified diff (file headers excluded).

    Used by ``compute_review_timeout`` to size the codex subprocess budget.
    Lines starting with ``+++`` / ``---`` are file headers, not changes — they
    are filtered out so a 50-file diff with one-line edits is not credited
    100 changes.
    """
    total = 0
    for line in diff.splitlines():
        if line.startswith(("+++", "---")):
            continue
        if line and line[0] in "+-":
            total += 1
    return total


def compute_review_timeout(diff: str) -> tuple[int, float]:
    """Return ``(changed_lines, timeout_seconds)`` for a codex review subprocess.

    Curve: ``base + per_line * lines`` clamped to ``cap``. See the
    ``REVIEW_TIMEOUT_*`` constants for the parameters and the rationale.
    Callers pass the same diff they'll send to the agent so the budget
    reflects the work the subprocess actually has to do.
    """
    lines = count_changed_lines(diff)
    timeout = REVIEW_TIMEOUT_BASE_SECONDS + lines * REVIEW_TIMEOUT_PER_LINE_SECONDS
    return lines, min(REVIEW_TIMEOUT_CAP_SECONDS, timeout)


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
    """Return True if the configured codex review agent command exists on PATH."""
    return shutil.which(settings.review_agent_cmd) is not None


def is_opencode_available() -> bool:
    """Return True if the configured opencode command exists on PATH.

    T-248 adds opencode as stage A of the two-stage sequencer. This helper
    lets ``app.py`` lifespan probe both binaries independently so a host with
    codex installed but opencode missing (or vice versa) is detected at boot
    — not at the first review-turn subprocess spawn (spec §5.4).
    """
    return shutil.which(settings.opencode_cmd) is not None


def resolve_review_source_root() -> Path:
    """Resolve the host-level fallback filesystem root codex will read.

    Used at backend boot (``log_review_source_root``) and as the fallback
    branch inside the per-PR resolver (``resolve_pr_review_root``) when no
    worktree row matches. T-278 introduced the per-PR resolver; this helper
    remains the correct answer for the boot log and for PRs whose owning
    worktree is not on this host.
    """
    return settings.review_source_root or Path.cwd()


@dataclass(frozen=True)
class PrReviewRoot:
    """Resolved filesystem root codex should read for this PR.

    ``path`` is always valid for the caller to hand to ``CodexReviewer`` /
    ``OpencodeReviewer``. When ``is_temp`` is True, ``path`` is a disposable
    ``git worktree add --detach`` checkout materialized at the PR's
    ``head_sha``; the caller MUST remove it via
    ``_remove_review_checkout(main_clone, path)`` (typically in a
    ``finally`` block) after the review finishes, otherwise
    ``.cloglog/review-checkouts/`` grows without bound. ``main_clone`` is
    the repository that owns the disposable worktree — the ``git -C
    <main_clone> worktree remove --force <path>`` anchor point. T-281.
    """

    path: Path
    is_temp: bool = False
    main_clone: Path | None = None


async def resolve_pr_review_root(
    event: WebhookEvent,
    *,
    project_id: UUID,
    worktree_query: IWorktreeQuery,
) -> PrReviewRoot | None:
    """Resolve the filesystem root codex should read for this PR.

    Preference order:

    **Path 0 — task pr_url binding (T-281).** If there is a ``Task`` in
    this project whose ``pr_url == event.pr_url`` and whose ``worktree_id``
    points at a known worktree, return that worktree's path. This is the
    ONLY path that resolves main-agent close-out PRs: the main agent has
    no worktree row keyed by the close-out branch (spawning one would
    cause infinite recursion), so ``find_by_branch`` misses.
    ``update_task_status(close_off_task_id, "review", pr_url=...)`` is the
    act that binds the PR to the main agent's worktree row; this path
    unwinds that binding. For typical agent PRs it resolves to the same
    worktree ``find_by_branch`` would — same answer, more direct route.

    **Path 1 — branch lookup (T-278).** Fall through to
    ``worktrees.branch_name == event.head_branch`` within the project.

    **Path 2 — per-repo registry (T-350).** Consult
    ``settings.review_repo_roots[event.repo_full_name]``. The map keys
    are ``owner/repo`` strings; the value is an absolute filesystem
    path. This path catches close-wave/hand-created PRs that have no
    registered worktree on the host — without it, those PRs would
    inherit the wrong repo's source via Path 3.

    **Path 3 — host-level fallback (T-255, legacy).**
    ``settings.review_source_root or Path.cwd()`` for PRs whose owning
    worktree is not on this host. Only consulted when
    ``settings.review_repo_roots`` is EMPTY (legacy single-repo
    deployment). When the registry is populated, this path is replaced
    by an explicit refusal: the resolver returns ``None`` for any
    ``repo_full_name`` not in the registry — surfaced to the caller
    as a one-shot ``unconfigured_repo`` skip comment instead of a
    cross-repo review (T-350; the antisocial PR #2 incident).

    **SHA-check + temp-dir fallback (T-281).** Whichever candidate the
    chain yields, we probe ``git -C <candidate> rev-parse HEAD``. If the
    candidate's HEAD disagrees with ``event.head_sha`` (race between push
    and webhook arrival; main clone trailing main; mid-rebase worktree),
    we materialize a disposable checkout at ``head_sha`` under
    ``<main_clone>/.cloglog/review-checkouts/<head_sha[:8]>-<pr_number>``
    and return that path with ``is_temp=True``. The caller cleans it up.
    If the temp-dir creation fails (SHA not fetchable, fs error), we fall
    through to the stale candidate with a ``review_source_drift`` warning.

    This resolver never mutates the OWNING worktree: no ``git fetch`` on
    it, no ``checkout``, no ``reset``. The owning agent controls its own
    working tree. The optional temp-dir checkout lives under the main
    clone's ``.cloglog/review-checkouts/`` — never an agent's worktree.
    """
    fallback = resolve_review_source_root()
    head_sha = (event.raw.get("pull_request") or {}).get("head", {}).get("sha", "") or ""
    head_branch = event.head_branch

    candidate: Path | None = None

    # Path 0 — pr_url binding chain
    try:
        row = await worktree_query.find_by_pr_url(project_id, event.pr_url)
    except Exception as err:  # noqa: BLE001 - defensive; a malformed event must not block review
        logger.warning(
            "find_by_pr_url failed for PR #%d: %s — falling through to branch lookup",
            event.pr_number,
            err,
        )
        row = None
    if row is not None:
        cand = Path(row.worktree_path)
        if cand.is_dir():
            candidate = cand
            logger.info(
                "review_source=worktree_pr_url path=%s pr=#%d",
                candidate,
                event.pr_number,
            )
        else:
            logger.warning(
                "review_source=fallback reason=path_missing source=worktree_pr_url "
                "worktree_path=%s pr=#%d",
                row.worktree_path,
                event.pr_number,
            )

    # Path 1 — branch lookup
    if candidate is None and head_branch:
        row = await worktree_query.find_by_branch(project_id, head_branch)
        if row is not None:
            cand = Path(row.worktree_path)
            if cand.is_dir():
                candidate = cand
                logger.info(
                    "review_source=worktree path=%s branch=%s pr=#%d",
                    candidate,
                    head_branch,
                    event.pr_number,
                )
            else:
                logger.warning(
                    "review_source=fallback reason=path_missing pr_branch=%s "
                    "worktree_path=%s pr=#%d",
                    head_branch,
                    row.worktree_path,
                    event.pr_number,
                )

    # Path 2 — per-repo registry (T-350)
    if candidate is None:
        registry_entry = settings.review_repo_roots.get(event.repo_full_name)
        if registry_entry is not None:
            cand = Path(registry_entry)
            # Codex round 5 HIGH: validate via ``--git-common-dir`` rather
            # than ``is_dir()`` alone. A mistyped registry value pointing
            # at an existing non-git directory was being accepted as a
            # successful registry hit; codex/opencode would then review
            # the wrong tree (or empty dir) instead of refusing. The
            # probe also catches a path that vanished after backend boot.
            if _git_common_dir(cand) is not None:
                candidate = cand
                logger.info(
                    "review_source=registry path=%s repo=%s pr=#%d",
                    candidate,
                    event.repo_full_name,
                    event.pr_number,
                )
            else:
                logger.warning(
                    "review_source=fallback reason=registry_path_invalid "
                    "repo=%s registry_path=%s pr=#%d "
                    "(path is missing or not a git repo)",
                    event.repo_full_name,
                    registry_entry,
                    event.pr_number,
                )

    # Path 3 — host-level fallback OR refusal
    if candidate is None:
        if settings.review_repo_roots:
            # Operator opted into the registry; an unmatched repo is a
            # configuration miss, not a fallback target. Refusing here
            # is the T-350 fix — the alternative is reviewing the PR
            # against the wrong repository's source.
            logger.warning(
                "review_source=refused reason=unconfigured_repo repo=%s pr_branch=%s pr=#%d",
                event.repo_full_name,
                head_branch or "<empty>",
                event.pr_number,
            )
            return None
        logger.warning(
            "review_source=fallback reason=no_matching_worktree pr_branch=%s pr=#%d",
            head_branch or "<empty>",
            event.pr_number,
        )
        candidate = fallback

    # SHA-check + temp-dir fallback
    #
    # T-350 codex sessions 2/5 + 3/5: the temp-checkout MUST be
    # materialised inside the main clone of the PR's OWN repo —
    # ``main_clone`` is documented as "the repository that owns the
    # disposable worktree" (PrReviewRoot docstring). Anchoring at
    # ``fallback`` (= ``review_source_root``, typically cloglog-prod)
    # for a foreign-repo PR runs ``git worktree add ... <foreign sha>``
    # against cloglog-prod's object DB and ``git fetch origin
    # <foreign branch>`` against cloglog's origin — neither resolves
    # the foreign objects, so the temp-checkout silently degrades to
    # a stale review.
    #
    # Order of preference for the anchor:
    #   1. registry entry for the PR's repo (multi-repo backends),
    #   2. parent of the candidate's ``--git-common-dir`` — covers
    #      Path 0/1 worktree hits for a foreign repo NOT in the
    #      registry (codex round 3: an antisocial worktree row routed
    #      via Path 1 still needs the antisocial main clone, even
    #      when the operator only registered cloglog),
    #   3. legacy ``fallback`` (single-repo / no candidate).
    if head_sha:
        worktree_sha = _probe_git_head(candidate)
        if worktree_sha is not None and worktree_sha != head_sha:
            # Resolve the anchor lazily so we don't probe registry paths
            # (and emit warnings about misconfigured ones) on PRs where
            # SHAs match — the temp-checkout path won't run anyway.
            main_clone_anchor = _resolve_main_clone_anchor(
                candidate, event.repo_full_name, fallback
            )
            temp = await _create_review_checkout(
                main_clone_anchor,
                head_sha=head_sha,
                pr_number=event.pr_number,
                head_branch=head_branch,
            )
            if temp is not None:
                logger.info(
                    "review_source=temp_checkout path=%s pr_head=%s pr=#%d (candidate_sha=%s)",
                    temp,
                    head_sha[:7],
                    event.pr_number,
                    worktree_sha[:7],
                )
                return PrReviewRoot(path=temp, is_temp=True, main_clone=main_clone_anchor)
            logger.warning(
                "review_source_drift worktree_head=%s pr_head=%s pr_branch=%s "
                "worktree_path=%s pr=#%d (temp-dir checkout unavailable; "
                "reviewing stale candidate)",
                worktree_sha[:7],
                head_sha[:7],
                head_branch or "<empty>",
                candidate,
                event.pr_number,
            )

    return PrReviewRoot(path=candidate)


def _resolve_main_clone_anchor(candidate: Path | None, repo_full_name: str, fallback: Path) -> Path:
    """Pick the main-clone anchor for ``_create_review_checkout``.

    The temp-checkout helper materialises a disposable worktree under
    ``<anchor>/.cloglog/review-checkouts/`` via ``git worktree add`` and,
    on a fetch retry, runs ``git fetch origin <branch>`` from the same
    anchor. Both must run inside the PR's OWN repo or the SHA / refs
    won't resolve. Preference order matches the resolver's path order:

    1. ``settings.review_repo_roots[repo_full_name]`` — explicit
       operator config wins (multi-repo backends), **but only if the
       configured path is a real git repo on disk** (codex round 4: a
       stale/mistyped registry entry was silently overriding a valid
       Path 1 worktree hit and breaking the temp-checkout). Validates
       via ``_git_common_dir`` rather than ``is_dir()`` alone — the
       anchor must own a git object DB, not just exist as a directory.
    2. Parent of ``git -C <candidate> rev-parse --git-common-dir`` —
       a Path 0/1 worktree hit for a repo without a usable registry
       entry still has the right answer encoded in the worktree
       itself: a linked worktree's common-dir points at the main
       clone's ``.git``, whose parent is the main clone. Covers codex
       round 3's foreign-repo Path 1 hit (antisocial worktree on a
       host whose registry only lists cloglog).
    3. ``fallback`` — single-repo legacy path, or a candidate whose
       common-dir probe fails (very rare; ``_create_review_checkout``
       is best-effort either way).
    """
    registry_entry = settings.review_repo_roots.get(repo_full_name)
    if registry_entry is not None:
        registry_path = Path(registry_entry)
        # Validate via ``--git-common-dir`` — a typo'd/stale path that
        # happens to exist as a directory but is not a git repo would
        # still break ``git worktree add`` downstream. The probe also
        # protects against a path that vanished after backend boot.
        if _git_common_dir(registry_path) is not None:
            return registry_path
        logger.warning(
            "review_repo_roots[%s]=%s is not a usable git repo — "
            "falling through to candidate common-dir derivation",
            repo_full_name,
            registry_entry,
        )
    if candidate is not None:
        common_dir = _git_common_dir(candidate)
        if common_dir is not None:
            # ``.git`` parent is the main clone; for the main worktree
            # itself this is the worktree dir (== main clone), and for
            # a linked worktree it's the original repo. Either way the
            # resulting path owns the worktree list and the origin
            # remote that ``_create_review_checkout`` needs.
            return common_dir.parent
    return fallback


def _git_common_dir(path: Path) -> Path | None:
    """Probe ``git -C <path> rev-parse --git-common-dir``. Return the
    absolute path to the shared ``.git`` directory or ``None``.

    For a linked worktree, the result points at the main clone's
    ``.git`` (the source of truth for the object DB and remotes).
    For the main worktree, it points at the worktree's own ``.git``.
    Errors are swallowed — the caller falls through to its own
    fallback.
    """
    import subprocess  # local: keep top-level imports lean

    try:
        proc = subprocess.run(  # noqa: S603 -- fixed argv, path from trusted source
            ["git", "-C", str(path), "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as err:  # pragma: no cover - rare
        logger.warning("git rev-parse --git-common-dir probe failed for %s: %s", path, err)
        return None
    if proc.returncode != 0:
        return None
    common = proc.stdout.strip()
    if not common:
        return None
    common_path = Path(common)
    if not common_path.is_absolute():
        # Older git emits a relative path resolved against the working
        # tree — anchor at ``path`` so the result is always absolute,
        # avoiding cwd dependency in the caller.
        common_path = (path / common_path).resolve()
    return common_path


def _probe_git_head(path: Path) -> str | None:
    """Probe ``git -C <path> rev-parse HEAD``. Return the SHA or ``None``.

    ``None`` on any failure — probe errors never block the resolver.
    """
    import subprocess  # local: keep top-level imports lean

    try:
        proc = subprocess.run(  # noqa: S603 -- fixed argv, path from trusted source
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as err:  # pragma: no cover - rare
        logger.warning("git rev-parse HEAD probe failed for %s: %s", path, err)
        return None
    if proc.returncode != 0:
        return None
    sha = proc.stdout.strip()
    return sha or None


async def _create_review_checkout(
    main_clone: Path,
    *,
    head_sha: str,
    pr_number: int,
    head_branch: str | None = None,
) -> Path | None:
    """Materialize a detached-HEAD git worktree at ``head_sha``.

    Creates ``<main_clone>/.cloglog/review-checkouts/<head_sha[:8]>-<pr_number>``
    via ``git worktree add --detach``. If ``main_clone`` hasn't fetched
    the SHA yet (webhook race with ``make promote``), retries once after
    ``git fetch origin <head_branch>``.

    Returns ``None`` on any failure — the caller treats that as "fall
    through to the stale candidate with a drift warning." Safe to call
    concurrently on different SHAs because the target directory name is
    keyed by ``head_sha[:8]`` + ``pr_number``; a stale same-path reuse is
    cleaned before the retry. Never raises.
    """
    checkout_dir = main_clone / _REVIEW_CHECKOUT_SUBDIR / f"{head_sha[:8]}-{pr_number}"
    if checkout_dir.exists():
        current = _probe_git_head(checkout_dir)
        if current == head_sha:
            # A prior review on the same commit already materialized the
            # same SHA — reuse it. The caller cleans up either way.
            return checkout_dir
        if not await _git_worktree_remove(main_clone, checkout_dir):
            logger.warning(
                "review_source=temp_checkout_unavailable reason=stale_cleanup_failed "
                "path=%s pr=#%d",
                checkout_dir,
                pr_number,
            )
            return None
    try:
        checkout_dir.parent.mkdir(parents=True, exist_ok=True)
    except OSError as err:
        logger.warning(
            "Cannot create review-checkouts parent for PR #%d: %s",
            pr_number,
            err,
        )
        return None

    if await _git_worktree_add(main_clone, checkout_dir, head_sha):
        return checkout_dir

    # Retry after fetching — webhook may have raced ahead of the main
    # clone's fetch cadence.
    if (
        head_branch
        and await _git_fetch_branch(main_clone, head_branch)
        and await _git_worktree_add(main_clone, checkout_dir, head_sha)
    ):
        return checkout_dir

    return None


async def _remove_review_checkout(main_clone: Path, checkout_dir: Path) -> None:
    """Remove a disposable review checkout via ``git worktree remove --force``.

    Best-effort — never raises; failures are logged. A stuck temp
    worktree is eventually reclaimed by ``git worktree prune`` (or the
    next call's ``stale_cleanup`` branch if the same PR SHA recurs).
    """
    await _git_worktree_remove(main_clone, checkout_dir)


async def _git_worktree_add(main_clone: Path, target: Path, sha: str) -> bool:
    """Run ``git -C <main_clone> worktree add --detach <target> <sha>``."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(main_clone),
        "worktree",
        "add",
        "--detach",
        str(target),
        sha,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=_GIT_SUBPROC_TIMEOUT_SECONDS)
    except TimeoutError:
        proc.kill()
        with contextlib.suppress(ProcessLookupError):
            await proc.wait()
        logger.warning("git worktree add timed out for SHA %s", sha[:7])
        return False
    if proc.returncode != 0:
        logger.warning(
            "git worktree add failed (rc=%s) for SHA %s: %s",
            proc.returncode,
            sha[:7],
            stderr.decode(errors="replace")[:200],
        )
        return False
    return True


async def _git_fetch_branch(main_clone: Path, head_branch: str) -> bool:
    """Run ``git -C <main_clone> fetch origin <head_branch>`` to warm up
    the object database when the webhook races ahead of the main clone.
    """
    if not head_branch:
        return False
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(main_clone),
        "fetch",
        "origin",
        head_branch,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=_GIT_FETCH_TIMEOUT_SECONDS)
    except TimeoutError:
        proc.kill()
        with contextlib.suppress(ProcessLookupError):
            await proc.wait()
        logger.warning("git fetch origin %s timed out", head_branch)
        return False
    if proc.returncode != 0:
        logger.warning(
            "git fetch origin %s failed (rc=%s): %s",
            head_branch,
            proc.returncode,
            stderr.decode(errors="replace")[:200],
        )
        return False
    return True


async def _git_worktree_remove(main_clone: Path, target: Path) -> bool:
    """Run ``git -C <main_clone> worktree remove --force <target>``."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(main_clone),
        "worktree",
        "remove",
        "--force",
        str(target),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=_GIT_SUBPROC_TIMEOUT_SECONDS)
    except TimeoutError:
        proc.kill()
        with contextlib.suppress(ProcessLookupError):
            await proc.wait()
        logger.warning("git worktree remove timed out for %s", target)
        return False
    if proc.returncode != 0:
        logger.warning(
            "git worktree remove failed (rc=%s) for %s: %s",
            proc.returncode,
            target,
            stderr.decode(errors="replace")[:200],
        )
        return False
    return True


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


_SEVERE_SEVERITIES: Final = frozenset({"critical", "high"})


def _format_review_body(result: ReviewResult, orphans: list[ReviewFinding]) -> str:
    """Assemble the top-level review body with the summary and any orphan findings.

    When ``verdict == "approve"`` is contradicted by any ``critical``/``high``
    severity finding, the body prefix is demoted from ``:pass:`` to ``:warning:``
    so the GitHub review body reflects the real consensus state. This mirrors
    ``ReviewLoop._reached_consensus`` (``src/gateway/review_loop.py:124-149``),
    which refuses to short-circuit a contradictory approve — the two must stay
    aligned so the T-227 ``latest_codex_review_is_approval`` helper cannot treat
    a contradictory row as a real approval on webhook replay. Observed on
    PR #190 with gemma4-e4b-32k emitting ``:pass:`` + ``[CRITICAL]`` in the
    same turn (codex flagged the gap on PR #201 round 2 HIGH).
    """
    has_severe_finding = any(f.severity in _SEVERE_SEVERITIES for f in result.findings)
    effective_verdict = (
        "request_changes" if result.verdict == "approve" and has_severe_finding else result.verdict
    )
    verdict_icon = {
        "approve": "pass",
        "request_changes": "warning",
        "comment": "info",
    }.get(effective_verdict, "info")
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
    """Return how many **sessions** the codex bot has posted on this PR.

    A session = one full two-stage run against a single commit SHA. Multiple
    turn POSTs on the same commit count as one session (spec §6.3). Reviews
    without a ``commit_id`` (unlikely in practice) fall back to counting each
    as a distinct session.

    Uses ``GET /repos/{owner}/{repo}/pulls/{pr_number}/reviews`` and collapses
    entries whose ``user.login`` is the codex bot by ``commit_id``. Network
    failure raises — the caller currently skips on uncertainty.
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
    # Count distinct commit_ids (session count, not POST count). Fall back to
    # len(reviews) only if EVERY codex row is missing commit_id — otherwise one
    # legacy row without commit_id would spuriously inflate the count.
    commit_ids: set[str] = set()
    codex_rows = [r for r in reviews if (r.get("user") or {}).get("login") == _CODEX_BOT]
    for r in codex_rows:
        cid = r.get("commit_id")
        if cid:
            commit_ids.add(cid)
    if commit_ids:
        return len(commit_ids)
    # Legacy fallback: no commit_ids at all — back-compat with existing tests
    # that don't set ``commit_id`` in their mocked review payloads.
    return len(codex_rows)


async def latest_codex_review_is_approval(
    repo_full_name: str,
    pr_number: int,
    token: str,
    head_sha: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> bool:
    """Return whether the latest codex review of ``head_sha`` emitted ``:pass:``.

    Scoped to a single commit on purpose: an approval of commit A must NOT
    suppress review of a newly-pushed commit B. This aligns with the rest of
    the review pipeline, whose consensus and turn accounting are keyed on
    ``(pr_url, head_sha, stage)`` (``src/review/repository.py`` unique index;
    ``src/gateway/review_loop.py`` turn sequencer; ``docs/design/two-stage-pr-review.md``
    §3 "new push starts both stages from turn 1"). A PR-wide scope here would
    let an older commit's ``:pass:`` mask regressions introduced on a later push.

    Approval is encoded as the ``_APPROVE_BODY_PREFIX`` (``:pass:``) on the
    review body because ``post_review`` pins ``event="COMMENT"`` (bot never
    flips GitHub's merge state). Rows are filtered by ``commit_id == head_sha``
    — legacy rows without ``commit_id`` are deliberately excluded; they cannot
    prove an approval of *this* commit. GitHub's /reviews endpoint returns
    rows oldest-first by id, so the last matching row is the most recent.
    Returns False when ``head_sha`` is empty (caller couldn't resolve a
    commit to scope to) or when no codex review matches ``head_sha``.
    """
    if not head_sha:
        return False
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
    codex_rows = [
        r
        for r in reviews
        if (r.get("user") or {}).get("login") == _CODEX_BOT and r.get("commit_id") == head_sha
    ]
    if not codex_rows:
        return False
    body = (codex_rows[-1].get("body") or "").lstrip()
    return body.startswith(_APPROVE_BODY_PREFIX)


def _should_skip_for_cap(
    prior_sessions: int,
    latest_is_approval: bool,
) -> tuple[bool, bool]:
    """Pure decision helper for T-227 cap — returns ``(skip, is_backstop)``.

    Semantics:
    - ``(True, False)``  → latest bot review was an approval; skip silently
      (the author already has the ``:pass:`` signal).
    - ``(True, True)``   → session backstop reached without approval; skip
      AND post a skip comment so the author knows review is done.
    - ``(False, False)`` → proceed with the review.

    Approval beats the backstop: if ``latest_is_approval`` is True we always
    return the silent-skip branch, even when ``prior_sessions >= MAX_REVIEWS_PER_PR``.
    Posting a "maximum reached" comment on a PR the bot already approved
    would be confusing.
    """
    if latest_is_approval:
        return (True, False)
    if prior_sessions >= MAX_REVIEWS_PER_PR:
        return (True, True)
    return (False, False)


async def post_review(
    repo_full_name: str,
    pr_number: int,
    result: ReviewResult,
    diff: str,
    token: str,
    *,
    head_sha: str = "",
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
    payload: dict[str, object] = {
        "event": "COMMENT",
        "body": _format_review_body(result, orphans),
        "comments": inline,
    }
    if head_sha:
        payload["commit_id"] = head_sha
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


class _RegistryCtx:
    """Async context manager yielding an ``IReviewTurnRegistry`` bound to a session.

    Gateway obtains the registry via ``src.review.services.make_review_turn_registry``
    — the Open Host Service boundary per ``docs/ddd-context-map.md``. The
    concrete ``ReviewTurnRepository`` type is NOT imported from Gateway
    (PR #187 round 2 CRITICAL fix — previously this imported the repository
    directly, which is a priority-3 DDD violation).
    """

    def __init__(self, session_factory: Any) -> None:
        self._factory = session_factory
        self._session: Any = None

    async def __aenter__(self) -> IReviewTurnRegistry:
        from src.review.services import make_review_turn_registry

        self._session = self._factory()
        await self._session.__aenter__()
        return make_review_turn_registry(self._session)

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._session is not None:
            await self._session.__aexit__(exc_type, exc, tb)
            self._session = None


class _WorktreeQueryCtx:
    """Async context manager yielding an ``IWorktreeQuery`` bound to a session.

    Gateway obtains the query via ``src.agent.services.make_worktree_query``
    — the Open Host Service boundary for the Agent context. The concrete
    ``AgentRepository`` type is NOT imported from Gateway, matching the
    Review-context precedent (see ``_RegistryCtx`` above). T-278.
    """

    def __init__(self, session_factory: Any) -> None:
        self._factory = session_factory
        self._session: Any = None

    async def __aenter__(self) -> IWorktreeQuery:
        from src.agent.services import make_worktree_query

        self._session = self._factory()
        await self._session.__aenter__()
        return make_worktree_query(self._session)

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._session is not None:
            await self._session.__aexit__(exc_type, exc, tb)
            self._session = None


class ReviewEngineConsumer:
    """Webhook consumer that runs a local review agent on every PR push."""

    _handled = frozenset({WebhookEventType.PR_OPENED, WebhookEventType.PR_SYNCHRONIZE})

    def __init__(
        self,
        *,
        max_per_hour: int | None = None,
        codex_available: bool = True,
        opencode_available: bool = False,
        session_factory: Any | None = None,
        ci_dispatcher: Any | None = None,
    ) -> None:
        from src.gateway.review_loop import dispatch_ci_after_codex

        rate = max_per_hour if max_per_hour is not None else settings.review_max_per_hour
        self._rate_limiter = RateLimiter(max_per_hour=rate)
        self._lock = asyncio.Lock()
        self._codex_available = codex_available
        self._opencode_available = opencode_available
        self._session_factory = session_factory
        # T-377: default to the real httpx dispatcher; tests inject a fake.
        self._ci_dispatcher = ci_dispatcher or dispatch_ci_after_codex
        # T-381: in-flight rate-limit retries, keyed by (repo_full_name, pr_number).
        # The skip comment promises a retry; this dict makes that promise truthful
        # by holding the scheduled ``asyncio.Task``. A second push to the same PR
        # cancels the pending retry and reschedules with the newer event so the
        # eventual review runs on the latest head.
        self._pending_retries: dict[tuple[str, int], asyncio.Task[None]] = {}

    def handles(self, event: WebhookEvent) -> bool:
        # Skip if ANY reviewer bot authored the PR (prevents review-of-review
        # loops). Claude bot PRs SHOULD be reviewed — only reviewer bots
        # themselves are filtered. Using ``_REVIEWER_BOTS`` (not the older
        # ``_BOT_USERNAMES`` constant) so extending the set with a new
        # reviewer bot automatically extends this guard — see T-248 acceptance
        # criterion 6.
        if event.sender in _REVIEWER_BOTS:
            return False
        return event.type in self._handled

    async def handle(self, event: WebhookEvent) -> None:
        if not self._rate_limiter.allow():
            # T-381: do all bookkeeping (cancel/reserve/register) BEFORE
            # awaiting the skip-comment POST. Webhook dispatch wraps each
            # event in ``asyncio.create_task`` (`webhook_dispatcher.py`),
            # so two pushes for the same PR can run concurrently. If we
            # awaited ``_notify_skip`` first, registration order would be
            # determined by GitHub POST latency rather than webhook
            # arrival order — a slow first POST could overwrite a
            # newer-event registration with the stale event. The
            # synchronous-block-then-await shape keeps the dedupe
            # deterministic.
            permanent = self._rate_limiter.is_permanently_blocked()
            scheduled = False
            wait_seconds = 0.0
            if not permanent:
                # Use the queue-aware ``reserve()`` wake time per
                # reservation — NOT the shared ``seconds_until_next_slot()``
                # — so multiple same-batch retries don't all wake at the
                # first reopened slot (codex round 4).
                scheduled, wake = self._schedule_rate_limit_retry(event)
                if scheduled:
                    wait_seconds = max(0.0, wake - time.monotonic())
            comment_body = self._rate_limit_skip_comment(
                wait_seconds=wait_seconds,
                permanent=permanent,
                scheduled=scheduled,
            )
            logger.warning(
                "Review rate limit exceeded, skipping PR #%d (%s)",
                event.pr_number,
                event.repo_full_name,
            )
            await self._notify_skip(event, SkipReason.RATE_LIMIT, comment_body)
            return

        # T-381 race fix: a buffered retry for this PR may still be
        # sleeping. Cancel it synchronously and release its reservation —
        # the current event is now serving the slot the retry held.
        # Synchronous w.r.t. the event loop so a concurrent ``handle()``
        # for a different PR cannot observe the half-released state.
        retry_key = (event.repo_full_name, event.pr_number)
        pending = self._pending_retries.pop(retry_key, None)
        if pending is not None and not pending.done():
            pending.cancel()
            self._rate_limiter.release_reservation(getattr(pending, "_t381_wake", time.monotonic()))

        async with self._lock:
            try:
                await self._review_pr(event)
            except Exception:
                logger.exception(
                    "Review failed for PR #%d (%s)",
                    event.pr_number,
                    event.repo_full_name,
                )

    @staticmethod
    def _rate_limit_skip_comment(*, wait_seconds: float, permanent: bool, scheduled: bool) -> str:
        """Build the user-visible skip-comment body (T-381).

        Three operationally-distinct cases must produce three different
        bodies — the original "Will retry after ~N minutes" was a lie in
        two of them:

        - ``permanent`` (``REVIEW_MAX_PER_HOUR=0``): no retry will ever
          fire; say so explicitly.
        - ``not permanent and not scheduled``: capacity is full this
          hour, nothing was queued. Tell the author what to do.
        - ``scheduled``: the truthful original promise.
        """
        prefix = (
            f"Codex review skipped: rate limit exceeded "
            f"({settings.review_max_per_hour} reviews/hour). "
        )
        if scheduled:
            return prefix + f"Will retry after ~{int(wait_seconds // 60)} minutes."
        if permanent:
            return prefix + (
                "Automatic retry is disabled because REVIEW_MAX_PER_HOUR=0 "
                "permanently blocks reviews."
            )
        return prefix + (
            "All retry slots in the current hour are already reserved — "
            "push a new commit after the window resets to re-trigger."
        )

    def _schedule_rate_limit_retry(self, event: WebhookEvent) -> tuple[bool, float]:
        """Schedule a delayed retry for a rate-limited webhook event (T-381).

        Returns ``(scheduled, wake)``. ``scheduled`` is ``True`` if a
        retry task was created; ``wake`` is its monotonic-clock wake
        time (or ``0.0`` when not scheduled). Caller (``handle()``) uses
        the return value to pick a truthful skip-comment body — promising
        a retry is dishonest when no task was scheduled — and to compute
        the user-visible "Will retry after ~N minutes" delay.

        Dedupes by ``(repo, pr_number)``: a second push for a PR that
        already has a pending retry cancels the older task (releasing
        its reservation synchronously) before reserving a new one. The
        net-zero swap always succeeds, even when ``can_reserve()`` would
        reject a *new* PR, because the released slot is immediately
        re-claimed.

        Each reservation is assigned its own queue slot via
        ``RateLimiter.reserve()`` so multiple same-batch retries fire at
        distinct times — never bunching at the first reopened slot.
        Synchronous w.r.t. the event loop so the caller can run it inside
        an atomic no-await block.
        """
        key = (event.repo_full_name, event.pr_number)
        existing = self._pending_retries.pop(key, None)
        if existing is not None and not existing.done():
            existing.cancel()
            # Release synchronously — the cancelled task's CancelledError
            # branch must not also release, or the reservation count would
            # double-decrement on replacement.
            self._rate_limiter.release_reservation(
                getattr(existing, "_t381_wake", time.monotonic())
            )
        if not self._rate_limiter.can_reserve():
            # All capacity for the current hour is already promised. No
            # retry is queued — caller must reflect that in the comment.
            return False, 0.0
        wake = self._rate_limiter.reserve()
        delay = max(0.0, wake - time.monotonic()) + RATE_LIMIT_RETRY_BUFFER_SECONDS
        task = asyncio.create_task(self._run_rate_limit_retry(event, wake, delay))
        # Stash the wake time on the task so cancellation paths (success
        # path in ``handle()``, replacement above) can release the right
        # reservation entry.
        task._t381_wake = wake  # type: ignore[attr-defined]
        self._pending_retries[key] = task
        return True, wake

    async def _run_rate_limit_retry(self, event: WebhookEvent, wake: float, delay: float) -> None:
        """Sleep ``delay`` then run the review for a rate-limited PR (T-381).

        On wake, converts the reservation (keyed by ``wake``) into a real
        timestamp so the rolling window correctly accounts for the
        executed review. Cancellation (replacement push or success-path
        supersession) does NOT release the reservation here — the
        canceller already released it synchronously, so a second release
        would corrupt the queue.
        """
        key = (event.repo_full_name, event.pr_number)
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        # Reservation → timestamp. Atomic against the event loop.
        self._rate_limiter.consume_reservation(wake)
        try:
            async with self._lock:
                await self._review_pr(event)
        except Exception:
            logger.exception(
                "Rate-limit retry failed for PR #%d (%s)",
                event.pr_number,
                event.repo_full_name,
            )
        finally:
            # Only clear our own entry — a newer push may have replaced it
            # while ``_review_pr`` was running, and that task should keep
            # tracking under the same key.
            if self._pending_retries.get(key) is asyncio.current_task():
                self._pending_retries.pop(key, None)

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
        from src.gateway.github_token import (
            get_codex_reviewer_token,
            get_github_app_token,
            get_opencode_reviewer_token,
        )
        from src.gateway.review_loop import (
            CodexReviewer,
            OpencodeReviewer,
            ReviewLoop,
        )

        # Claude bot token for reading diffs (has contents:read).
        claude_token = await get_github_app_token()

        # Head SHA that triggered this webhook — needed up-front because the
        # T-227 approval check is per-commit (an approval of commit A must
        # not suppress review of a newly-pushed commit B). Falls through to
        # the degraded path further down if empty.
        head_sha = (event.raw.get("pull_request") or {}).get("head", {}).get("sha", "")

        # Per-PR session cap (spec §6.3, T-227): verdict-based with a backstop.
        # Skip further review when the latest codex review OF THE CURRENT head_sha
        # emitted ``:pass:`` (bot satisfied with THIS commit — author has the
        # signal). The count-based backstop at ``MAX_REVIEWS_PER_PR`` counts
        # PR-wide sessions and only fires when no approval has been reached on
        # the current head. Only applies when codex is runnable — opencode-only
        # hosts (spec §5.4 registration matrix row 3) skip the cap check; an
        # unconditional codex token fetch would blow up before stage A runs
        # (PR #187 round 1).
        #
        # ``prior`` also feeds the review-body header counter (T-290): the
        # per-turn header renders ``session {prior + 1}/{MAX_REVIEWS_PER_PR}``
        # so a reader can tell one codex comment on a PR from another. T-376:
        # ``prior`` is now the posted-review count, so the displayed number is
        # the post index, not the session-attempt index. Opencode-only hosts
        # have no session count and fall back to ``1`` — the cap is not
        # enforced there either.
        prior = 0
        if self._codex_available:
            codex_token_for_cap = await get_codex_reviewer_token()
            # T-376: count POSTED codex reviews from the registry, not session
            # attempts. A session that hits a non-post terminal (rate-limit
            # skip, codex_unavailable, post_failed) does not consume the cap
            # because the author never saw a review. Pre-T-376 the cap counted
            # ``count_bot_reviews`` (GitHub-side review count), which was
            # cap-correct for happy paths but wrong for non-post terminals.
            #
            # The registry path is gated on ``self._session_factory`` because
            # the degraded harness (no Review context wired up — see line ~1510
            # below) cannot read ``pr_review_turns``. In that path we fall back
            # to ``count_bot_reviews``; the degraded path is a single-turn
            # codex with no multi-session loop, so the cap there is best-effort.
            if self._session_factory is not None:
                async with self._registry() as registry_for_cap:
                    prior = await registry_for_cap.count_posted_codex_sessions(pr_url=event.pr_url)
            else:
                prior = await count_bot_reviews(
                    event.repo_full_name, event.pr_number, codex_token_for_cap
                )
            # Short-circuit: zero prior posts cannot include an approval, so
            # no need for the extra HTTP call.
            latest_is_approval = prior > 0 and await latest_codex_review_is_approval(
                event.repo_full_name,
                event.pr_number,
                codex_token_for_cap,
                head_sha,
            )
            skip, is_backstop = _should_skip_for_cap(prior, latest_is_approval)
            if skip and not is_backstop:
                logger.info(
                    "PR #%d: latest bot review is an approval (:pass:) — skipping further review",
                    event.pr_number,
                )
                return
            if skip and is_backstop:
                logger.info(
                    "PR #%d reached bot-review backstop "
                    "(%d sessions, cap=%d, no approval) — skipping",
                    event.pr_number,
                    prior,
                    MAX_REVIEWS_PER_PR,
                )
                await self._notify_skip(
                    event,
                    SkipReason.MAX_REVIEWS,
                    (
                        f"Review skipped: this PR reached the maximum of "
                        f"{MAX_REVIEWS_PER_PR} bot review sessions without the "
                        f"bot reaching approval. Request human review."
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
                    "Review skipped: no reviewable files after "
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
                    f"Review skipped: diff too large "
                    f"({len(filtered)} chars, cap {MAX_DIFF_CHARS}). "
                    f"Break into smaller PRs or request human review."
                ),
            )
            return

        # Resolve the turn registry + project_id. The sequencer writes turn-
        # accounting rows into ``pr_review_turns``; idempotency + reset rules
        # (spec §3.3/§3.4) depend on the registry being consulted every turn.
        # ``head_sha`` was resolved up-front for the T-227 cap check.
        if self._session_factory is None or not head_sha:
            logger.warning(
                "Review sequencer fell back to single-turn codex path for PR #%d "
                "(session_factory=%s, head_sha=%s)",
                event.pr_number,
                self._session_factory is not None,
                bool(head_sha),
            )
            # Single-turn degraded path so the backend boots even if the new
            # Review context isn't wired up in some test harness. Only runs
            # when codex is available — opencode-only hosts skip silently
            # (the degraded path predates the two-stage loop).
            if self._codex_available:
                review_token = await get_codex_reviewer_token()
                result = await self._run_review_agent(filtered, event, review_token)
                if result is not None:
                    await post_review(
                        event.repo_full_name,
                        event.pr_number,
                        result,
                        filtered,
                        review_token,
                        head_sha=head_sha,
                    )
            return

        project_id = await self._resolve_project_id(event)
        if project_id is None:
            logger.warning(
                "No project found for repo %s — skipping review for PR #%d",
                event.repo_full_name,
                event.pr_number,
            )
            return

        # T-278 / T-281: resolve the PR's owning worktree per review, not
        # once per backend process. The chain is Path 0 (tasks.pr_url →
        # task.worktree_id) → Path 1 (branch) → host-level fallback →
        # SHA-check + temp-dir checkout. When the resolver returns
        # ``is_temp=True``, the caller MUST clean up via
        # ``_remove_review_checkout`` — the ``finally`` block below does
        # that, including when stage A or B raises.
        async with self._worktree_query() as wq:
            review_root = await resolve_pr_review_root(
                event, project_id=project_id, worktree_query=wq
            )
        # T-350: when `review_repo_roots` is configured and the event's
        # repo isn't in it AND no worktree owns the branch, the resolver
        # refuses (None). Posting nothing is strictly better than
        # reviewing against the wrong repo's source — surface the refusal
        # as a one-shot skip comment so the operator can see the
        # configuration gap on GitHub.
        if review_root is None:
            await self._notify_skip(
                event,
                SkipReason.UNCONFIGURED_REPO,
                (
                    f"Code review skipped: this App is installed but not "
                    f"configured for review on `{event.repo_full_name}`. "
                    f"Configure `REVIEW_REPO_ROOTS` (env var or "
                    f"`review_repo_roots` in `src/shared/config.py`) on "
                    f"the cloglog backend to enable reviews for this repo."
                ),
            )
            return
        project_root = review_root.path

        # Session counter for the review-body header (T-290). ``prior`` counts
        # sessions already posted on earlier webhook firings; this firing is
        # session ``prior + 1``. Both stages use the same counter so Stage A
        # and Stage B reviews are labelled consistently within a session.
        session_index = prior + 1

        try:
            # ----- Stage A: opencode (gemma4:e4b) — up to opencode_max_turns -----
            # T-275: gated on settings.opencode_enabled so the stage can be silenced
            # globally without removing the code paths T-274 still needs. When the
            # flag is False, stage A is skipped exactly as if the binary were absent.
            if self._opencode_available and settings.opencode_enabled:
                try:
                    opencode_token = await get_opencode_reviewer_token()
                except FileNotFoundError as err:
                    # Host has the opencode binary but no PEM at
                    # ~/.agent-vm/credentials/opencode-reviewer.pem. Stage A is
                    # skipped; codex still runs. See docs/setup-credentials.md.
                    logger.info(
                        "Opencode reviewer PEM missing — skipping stage A for PR #%d (%s)",
                        event.pr_number,
                        err,
                    )
                    opencode_token = None
            else:
                opencode_token = None

            if opencode_token is not None:
                async with self._registry() as registry:
                    loop_a = ReviewLoop(
                        OpencodeReviewer(project_root),
                        max_turns=settings.opencode_max_turns,
                        registry=registry,
                        project_id=project_id,
                        pr_url=event.pr_url,
                        pr_number=event.pr_number,
                        repo_full_name=event.repo_full_name,
                        head_sha=head_sha,
                        stage="opencode",
                        reviewer_token=opencode_token,
                        session_index=session_index,
                        max_sessions=MAX_REVIEWS_PER_PR,
                    )
                    outcome_a = await loop_a.run(diff=filtered)
                if outcome_a.turns_used == 0 and outcome_a.errors:
                    # A completely failed stage A posts a single skip comment so
                    # the author knows why opencode produced nothing.
                    await self._notify_skip(
                        event,
                        SkipReason.OPENCODE_FAILED,
                        (
                            "Opencode stage A failed every turn. "
                            f"Reasons: {', '.join(outcome_a.errors[:3])}. "
                            "Codex (stage B) still runs."
                        ),
                    )

            # ----- Stage B: codex (Claude-API) — up to codex_max_turns -----
            if self._codex_available:
                review_token = await get_codex_reviewer_token()
                # T-367 cross-push memory: fetch every prior completed codex
                # turn on this PR (across pushes — keyed by pr_url, NOT by
                # head_sha) so CodexReviewer can render the "Prior review
                # history" preamble. Returns an empty PriorContext on the
                # first webhook for a PR — preamble is then suppressed.
                # Also lift the PR body from the webhook payload so codex
                # gets the human-equivalent context (pull_request_template
                # sections an agent filled).
                pr_body = (event.raw.get("pull_request") or {}).get("body") or ""
                async with self._registry() as registry:
                    prior_context = await registry.prior_findings_and_learnings(
                        pr_url=event.pr_url, stage="codex"
                    )
                    loop_b = ReviewLoop(
                        CodexReviewer(project_root),
                        max_turns=settings.codex_max_turns,
                        registry=registry,
                        project_id=project_id,
                        pr_url=event.pr_url,
                        pr_number=event.pr_number,
                        repo_full_name=event.repo_full_name,
                        head_sha=head_sha,
                        stage="codex",
                        reviewer_token=review_token,
                        session_index=session_index,
                        max_sessions=MAX_REVIEWS_PER_PR,
                        # T-374 main-inbox + skip-comment finalization plumbing.
                        session_factory=self._session_factory,
                        head_branch=event.head_branch,
                        # T-377: only the codex stage fires CI; opencode is
                        # advisory and never gates merge. Inject the
                        # dispatcher as a hook so unit tests can pin the
                        # firing rule with a fake — see
                        # tests/gateway/test_review_loop_t377_ci_dispatch.py.
                        ci_dispatcher=self._ci_dispatcher,
                    )
                    outcome_b = await loop_b.run(
                        diff=filtered,
                        prior_context=prior_context,
                        pr_body=pr_body,
                    )
                    # T-374 (codex round 1 HIGH): finalize a codex timeout
                    # the same way the legacy ``_run_review_agent`` path
                    # does — probe codex/github liveness, format the
                    # AGENT_TIMEOUT body, and post the skip comment as
                    # the codex bot. Without this, a sequenced-path
                    # timeout produces no PR comment at all, recreating
                    # the silent-timeout regression. The inbox event
                    # ``ReviewLoop`` already emitted is an additional
                    # supervisor-side signal, not the only user-visible
                    # one.
                    if getattr(outcome_b, "last_timed_out", False):
                        codex_alive, codex_detail = await _probe_codex_alive()
                        github_reachable, github_detail = await _probe_github_reachable()
                        timeout_outcome = _AgentAttemptOutcome(
                            result=None,
                            timed_out=True,
                            stderr_excerpt=outcome_b.last_timeout_stderr_excerpt,
                            elapsed_seconds=outcome_b.last_timeout_elapsed_seconds,
                        )
                        body = _format_timeout_body(
                            timeout_outcome,
                            codex_alive,
                            codex_detail,
                            github_reachable,
                            github_detail,
                            outcome_b.last_timeout_seconds,
                        )
                        await self._post_agent_skip(
                            event, SkipReason.AGENT_TIMEOUT, body, review_token
                        )
                        # T-374 codex round 5 HIGH: emit the supervisor
                        # event ONLY when the codex stage has actually
                        # ended in timeout — i.e. after this terminal
                        # check, not from inside ``ReviewLoop.run``'s
                        # per-turn branch (which can fire on a
                        # non-terminal timeout when ``codex_max_turns >
                        # 1`` and a later turn succeeds).
                        await emit_codex_review_timed_out(
                            pr_url=event.pr_url,
                            pr_number=event.pr_number,
                            repo_full_name=event.repo_full_name,
                            head_branch=event.head_branch,
                            diff_size=outcome_b.last_timeout_diff_lines,
                            timeout_seconds=outcome_b.last_timeout_seconds,
                            session_factory=self._session_factory,
                        )
            logger.info(
                "review_session_end pr=%d repo=%s",
                event.pr_number,
                event.repo_full_name,
            )
        finally:
            if review_root.is_temp and review_root.main_clone is not None:
                await _remove_review_checkout(review_root.main_clone, review_root.path)

    def _registry(self) -> _RegistryCtx:
        """Context manager that yields an ``IReviewTurnRegistry`` bound to a session."""
        from src.shared.database import async_session_factory

        factory = self._session_factory or async_session_factory
        return _RegistryCtx(factory)

    def _worktree_query(self) -> _WorktreeQueryCtx:
        """Context manager that yields an ``IWorktreeQuery`` bound to a session.

        Used by ``_review_pr`` to resolve the PR's owning worktree before
        constructing reviewers — see T-278.
        """
        from src.shared.database import async_session_factory

        factory = self._session_factory or async_session_factory
        return _WorktreeQueryCtx(factory)

    async def _resolve_project_id(self, event: WebhookEvent) -> UUID | None:
        """Resolve the project UUID for this webhook event's repo."""
        from src.board.repository import BoardRepository
        from src.shared.database import async_session_factory

        factory = self._session_factory or async_session_factory
        async with factory() as session:
            repo = BoardRepository(session)
            project = await repo.find_project_by_repo(event.repo_full_name)
            return project.id if project is not None else None

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
        # T-350 codex round 5 MEDIUM: the degraded single-turn path
        # cannot bypass the per-repo refusal. ``_review_pr``'s sequenced
        # branch routes through ``resolve_pr_review_root`` and refuses
        # unconfigured repos with ``UNCONFIGURED_REPO``; without this
        # block, any caller that takes the degraded branch (no
        # ``session_factory``, missing ``head_sha``, or older harnesses
        # constructing ``ReviewEngineConsumer()`` with no factory) would
        # still review against ``settings.review_source_root`` and
        # recreate the cross-repo leak.
        #
        # The degraded path skips the per-PR worktree lookup (which
        # requires DB session machinery the degraded branch was added
        # to avoid), so we apply the registry-only subset of the
        # refusal contract: when ``review_repo_roots`` is populated and
        # the event's repo isn't in it (or is mapped to an invalid
        # path), refuse. When the registry is empty (single-repo legacy
        # hosts) we keep the historical fallback unchanged.
        if settings.review_repo_roots:
            registry_entry = settings.review_repo_roots.get(event.repo_full_name)
            if registry_entry is None:
                logger.warning(
                    "Degraded review path: review_repo_roots configured but "
                    "no entry for %s — refusing rather than reviewing against "
                    "review_source_root (T-350)",
                    event.repo_full_name,
                )
                await self._notify_skip(
                    event,
                    SkipReason.UNCONFIGURED_REPO,
                    (
                        f"Code review skipped: this App is installed but not "
                        f"configured for review on `{event.repo_full_name}`. "
                        f"Configure `REVIEW_REPO_ROOTS` (env var or "
                        f"`review_repo_roots` in `src/shared/config.py`) on "
                        f"the cloglog backend to enable reviews for this repo."
                    ),
                )
                return None
            registry_path = Path(registry_entry)
            if _git_common_dir(registry_path) is None:
                logger.warning(
                    "Degraded review path: review_repo_roots[%s]=%s is not "
                    "a usable git repo — refusing (T-350 round 5)",
                    event.repo_full_name,
                    registry_entry,
                )
                await self._notify_skip(
                    event,
                    SkipReason.UNCONFIGURED_REPO,
                    (
                        f"Code review skipped: `REVIEW_REPO_ROOTS` entry for "
                        f"`{event.repo_full_name}` points at "
                        f"`{registry_entry}`, which is not a git repo. "
                        f"Fix the configuration on the cloglog backend."
                    ),
                )
                return None
            project_root = registry_path
        else:
            # Legacy single-repo path — `settings.review_source_root` must
            # point at a checkout of the PR's merge target (usually main).
            # When unset, fall back to Path.cwd() — fine for dev, wrong in
            # prod where the backend runs out of a prod checkout that
            # trails main. See T-255.
            project_root = settings.review_source_root or Path.cwd()
        prompt = _load_project_prompt(project_root)
        schema_path = _get_schema_path(project_root)
        full_prompt = f"{prompt}\n\nDIFF:\n{diff}"
        diff_lines, timeout_seconds = compute_review_timeout(diff)

        last_outcome: _AgentAttemptOutcome | None = None
        # Matches T-229's retry philosophy: one retry swallows a transient
        # stall; a second consecutive timeout is systemic and must surface.
        for attempt in (1, 2):
            outcome = await self._run_agent_once(
                full_prompt, project_root, schema_path, event.pr_number, timeout_seconds
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
                    "diff_size": diff_lines,
                    "timeout_seconds": timeout_seconds,
                }
                logger.warning("review_timeout %s", log_entry)
                await emit_codex_review_timed_out(
                    pr_url=event.pr_url,
                    pr_number=event.pr_number,
                    repo_full_name=event.repo_full_name,
                    head_branch=event.head_branch,
                    diff_size=diff_lines,
                    timeout_seconds=timeout_seconds,
                    session_factory=self._session_factory,
                )
                body = _format_timeout_body(
                    outcome,
                    codex_alive,
                    codex_detail,
                    github_reachable,
                    github_detail,
                    timeout_seconds,
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
        timeout_seconds: float = REVIEW_TIMEOUT_BASE_SECONDS,
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
                    timeout=timeout_seconds,
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
        """Try to parse review output — thin wrapper around module-level helper."""
        return parse_reviewer_output(raw, pr_number)


def parse_reviewer_output(raw: str, pr_number: int | None = None) -> ReviewResult | None:
    """Parse raw reviewer stdout into ``ReviewResult``, or ``None`` on failure.

    Handles both the internal ``{verdict, summary, findings}`` schema and the
    Codex ``--output-schema`` format (``findings[].code_location``,
    ``overall_correctness``). The Codex path normalizes findings into the
    internal shape while PRESERVING the optional top-level ``status`` field
    (spec §7.1 — losing this was the MEDIUM finding on PR #185 round 1).

    ``pr_number`` is informational only (appears in warning logs).
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
        # Codex schema format — convert. Preserve the optional top-level
        # `status` field so the ReviewLoop's explicit-consensus check sees it
        # (spec §7.1; losing this in the rewrite was the MEDIUM finding on
        # PR #185 round 1 that triggered the T-261 re-work).
        is_correct = data.get("overall_correctness") == "patch is correct"
        verdict = "approve" if is_correct else "request_changes"
        status = data.get("status")
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
                    # Keep the title too so ReviewLoop's predicate (b)
                    # (zero-new-findings across prior turns) has a stable
                    # key per spec §1.1.
                    "title": f.get("title", ""),
                }
            )
        # T-367: carry the optional learnings array through. Codex emits a
        # list of {"topic", "note"} objects per the extended review-schema;
        # absent / empty / wrong-type all collapse to []. Persisted by
        # ReviewLoop into pr_review_turns.learnings_json for cross-push
        # replay.
        raw_learnings = data.get("learnings") or []
        learnings: list[dict[str, Any]] = (
            [item for item in raw_learnings if isinstance(item, dict)]
            if isinstance(raw_learnings, list)
            else []
        )
        data = {
            "verdict": verdict,
            "summary": data.get("overall_explanation", ""),
            "findings": findings,
            "status": status,
            "learnings": learnings,
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
    timeout_seconds: float = REVIEW_TIMEOUT_BASE_SECONDS,
) -> str:
    """PR comment body for a post-retry timeout."""
    lines = [
        f"Codex review failed: agent timed out after "
        f"{int(timeout_seconds)}s (retried once). "
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


async def _probe_opencode_alive() -> tuple[bool, str]:
    """Check the opencode binary responds to ``--version``.

    Returns ``(alive, detail)``. Never raises — diagnostics only.
    Mirrors ``_probe_codex_alive`` exactly so the same health-check shape
    works for both reviewer binaries (spec §5.4).
    """
    try:
        proc = await _create_subprocess(
            settings.opencode_cmd,
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
