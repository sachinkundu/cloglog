"""Protocols exposed by the Review context.

Gateway's two-stage review sequencer depends on ``IReviewTurnRegistry`` —
a Protocol — and never imports the concrete repository or SQLAlchemy model.
This is the Open Host Service boundary in ``docs/ddd-context-map.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Final, Protocol
from uuid import UUID


@dataclass(frozen=True)
class ReviewTurnSnapshot:
    """Read-only snapshot of a single persisted turn.

    Carried across the Gateway→Review boundary instead of the ORM row so
    Gateway never binds to ``src.review.models``.
    """

    project_id: UUID
    pr_url: str
    pr_number: int
    head_sha: str
    stage: str
    turn_number: int
    status: str
    finding_count: int | None
    consensus_reached: bool
    elapsed_seconds: float | None
    # T-375: cross-session counter recorded at ``claim_turn`` time and the
    # timestamp set by ``mark_posted`` after a successful GitHub review POST.
    # Together they let ReviewLoop short-circuit a duplicate post inside the
    # same logical session without re-querying GitHub.
    session_index: int | None = None
    posted_at: datetime | None = None
    # T-407: set to 'db_error' when findings/learnings persistence failed.
    outcome: str | None = None


@dataclass(frozen=True)
class PriorTurnSummary:
    """One prior turn's findings + learnings, as carried into a later turn's prompt.

    Carries everything the next turn needs to render its preamble without
    re-fetching from the database. ``findings`` is the raw JSON array as codex
    emitted it (validated against ``.github/codex/review-schema.json``);
    ``learnings`` is the optional ``learnings`` array from the same schema
    (empty list if codex didn't emit any). ``head_sha`` is included so the
    preamble can group findings by commit ("turn 1 on abc123 found …").

    ``author_responses`` maps the string representation of a finding's index
    (``str(i)`` where ``i`` is the 0-based position in ``findings``) to the
    latest PR-author reply on that finding's GitHub review-comment thread.
    ``None`` value means no reply was found; absent key means the same.
    Populated by ``src.gateway.review_thread_replies.enrich_prior_context``
    after the registry fetch; empty dict when running without a GitHub token
    (e.g. tests).
    """

    head_sha: str
    turn_number: int
    findings: list[dict[str, Any]] = field(default_factory=list)
    learnings: list[dict[str, Any]] = field(default_factory=list)
    author_responses: dict[str, str | None] = field(default_factory=dict)


@dataclass(frozen=True)
class PriorContext:
    """PR-life-aggregated prior turns for the codex stage.

    Returned by ``IReviewTurnRegistry.prior_findings_and_learnings`` and used
    by the Gateway sequencer to build the "Prior review history" preamble for
    turn N (N ≥ 2). Excludes turns whose status is not ``completed`` —
    failed/timed-out turns have nothing to replay.
    """

    pr_url: str
    turns: list[PriorTurnSummary] = field(default_factory=list)

    @property
    def codex_turn_count(self) -> int:
        """Number of completed codex turns on this PR. Used to enforce the
        5-turn lifetime cap."""
        return len(self.turns)


MAX_REVIEWS_PER_PR: Final[int] = 5
"""Lifetime cap on bot codex review *sessions* per PR (T-227 / T-376).

Counts distinct ``session_index`` values over rows where ``posted_at IS NOT
NULL`` for ``stage='codex'``. Lives on the Review interface so both the
Gateway review loop (which enforces the cap) and the Board projection
(which renders the EXHAUSTED badge — T-424) can reference one source of
truth without Board importing from Gateway.
"""


class CodexStatus(StrEnum):
    """Discriminated codex review state for a single PR.

    Projected by ``IReviewTurnRegistry.codex_status_by_pr`` for the Board
    context. Each value maps to a distinct badge on the Kanban card so an
    operator can answer "is codex working / done / stuck" at a glance without
    grepping logs. ``NOT_STARTED`` renders no badge.
    """

    NOT_STARTED = "not_started"
    WORKING = "working"
    PROGRESS = "progress"
    PASS = "pass"
    EXHAUSTED = "exhausted"
    FAILED = "failed"
    STALE = "stale"


@dataclass(frozen=True)
class CodexProgress:
    """Turn-level detail for the ``PROGRESS`` state.

    Carried alongside ``CodexStatus.PROGRESS`` so the board can render
    ``codex N/M`` without a second query.
    """

    turn: int
    max_turns: int
    sha: str


@dataclass(frozen=True)
class CodexStatusResult:
    """Combined codex status + optional progress for one PR."""

    status: CodexStatus
    progress: CodexProgress | None = None


class IReviewTurnRegistry(Protocol):
    """Persistent turn accounting for the two-stage review pipeline."""

    async def claim_turn(
        self,
        *,
        project_id: UUID,
        pr_url: str,
        pr_number: int,
        head_sha: str,
        stage: str,
        turn_number: int,
        session_index: int | None = None,
    ) -> bool:
        """Atomically insert a ``running`` turn row.

        Returns ``True`` iff this caller won the slot. ``False`` means another
        handler already claimed the same ``(pr_url, head_sha, stage, turn_number)``
        — the caller must exit without running the subprocess.

        Implementation uses ``INSERT ... ON CONFLICT DO NOTHING`` on the
        unique index ``uq_pr_review_turns_key``.

        ``session_index`` (T-375 / T-376) is the cross-session counter
        stamped on the row so a webhook re-fire on the same SHA can detect
        "this session already posted" via ``posted_at``. T-376 changed the
        counter source from GitHub-review count to
        ``count_posted_codex_sessions + 1`` so the cap counts actual posted
        reviews, not session attempts. Optional with default ``None`` for
        back-compat; new ReviewLoop callers always pass it.
        """
        ...

    async def complete_turn(
        self,
        *,
        pr_url: str,
        head_sha: str,
        stage: str,
        turn_number: int,
        status: str,
        finding_count: int | None,
        consensus_reached: bool,
        elapsed_seconds: float,
    ) -> None:
        """Mark a previously claimed turn as terminal (completed / timed_out / failed)."""
        ...

    async def latest_for(self, pr_url: str, head_sha: str) -> ReviewTurnSnapshot | None:
        """Return the most recently-created row for ``(pr_url, head_sha)``, or None.

        Used by the dashboard to render the ``opencode 2/5`` / ``codex 1/2`` badge
        (see ``docs/design/two-stage-pr-review.md`` §8.3).
        """
        ...

    async def turns_for_stage(
        self,
        *,
        pr_url: str,
        head_sha: str,
        stage: str,
    ) -> list[ReviewTurnSnapshot]:
        """Return every turn for a single (pr_url, head_sha, stage), oldest first.

        Used by the consensus checker to compute predicate (b) — zero-new-findings
        across the union of all prior turns.
        """
        ...

    async def mark_posted(
        self,
        *,
        pr_url: str,
        head_sha: str,
        stage: str,
        turn_number: int,
    ) -> bool:
        """Stamp ``posted_at = now()`` on a turn row after a successful POST.

        Returns ``True`` iff the row existed with NULL ``posted_at`` and
        was updated. A second call on a row that already carries
        ``posted_at`` returns ``False`` (no-op) so a webhook re-fire is a
        clean noop. There is intentionally no DB-level uniqueness across
        rows: the per-turn POST contract
        (``docs/design/two-stage-pr-review.md`` §3.3) allows multiple
        successful posts within one session when ``codex_max_turns > 1``.
        T-375.
        """
        ...

    async def count_posted_codex_sessions(self, *, pr_url: str) -> int:
        """Return the number of distinct codex sessions that have posted on this PR.

        T-376: the per-PR cap (``MAX_REVIEWS_PER_PR``) counts POSTED
        reviews, not session attempts. A session that hits a non-post
        terminal (rate-limit skip, codex unavailable, post_failed) does
        NOT consume the cap because it never produced a review the
        author can read.

        Implementation: distinct ``session_index`` over rows where
        ``stage='codex'`` and ``posted_at IS NOT NULL``. Rows from before
        T-375 (``session_index IS NULL``) are not counted — pre-T-375
        rows belong to PRs that have either merged or rolled past the
        upgrade window; the upgrade-window cost is at most a few extra
        reviews on a long-lived PR straddling the deploy.
        """
        ...

    async def reset_to_running(
        self,
        *,
        pr_url: str,
        head_sha: str,
        stage: str,
        turn_number: int,
    ) -> bool:
        """Flip a ``failed`` turn back to ``running`` so the loop can retry it.

        Returns ``True`` iff the row existed with ``status='failed'`` and was
        updated. ``False`` means no such row (another handler already re-ran,
        or the turn never existed, or it is in a terminal non-failed state).
        Used on webhook re-fire to retry a turn whose GitHub review POST
        previously failed — see PR #187 round 1 HIGH-3 fix.
        """
        ...

    async def record_findings_and_learnings(
        self,
        *,
        pr_url: str,
        head_sha: str,
        stage: str,
        turn_number: int,
        findings_json: list[dict[str, Any]],
        learnings_json: list[dict[str, Any]],
    ) -> None:
        """Persist the codex findings array + learnings array for one turn.

        Called by the Gateway sequencer after a codex review completes
        successfully (the JSON parsed cleanly and validated against the
        review schema). Idempotent on re-call: if the row already carries
        non-null findings/learnings, this overwrites — caller is responsible
        for not double-running. T-367 cross-push memory.
        """
        ...

    async def prior_findings_and_learnings(
        self,
        *,
        pr_url: str,
        stage: str,
    ) -> PriorContext:
        """Aggregate all completed prior turns of ``stage`` for this PR.

        PR-scoped (not commit-scoped) because a fix-up commit changes
        ``head_sha`` but the prior findings/learnings are still the relevant
        memory for the next turn's prompt. Returns turns oldest-first. Only
        includes turns with ``status='completed'`` AND non-null
        ``findings_json`` — failed/timed-out turns have nothing to replay,
        and a row created by ``claim_turn`` but never written by
        ``record_findings_and_learnings`` would carry zero findings and zero
        learnings (a meaningless preamble entry).
        """
        ...

    async def set_outcome(
        self,
        *,
        pr_url: str,
        head_sha: str,
        stage: str,
        turn_number: int,
        outcome: str,
    ) -> None:
        """Stamp an outcome marker on a turn row after a persistence failure.

        Called best-effort after catching a DBAPIError from
        ``record_findings_and_learnings``. The caller must ensure the session
        is clean (rolled back) before calling this. T-407/T-409.
        """
        ...

    async def codex_touched_pr_urls(self, *, project_id: UUID, pr_urls: list[str]) -> set[str]:
        """Return the subset of ``pr_urls`` with at least one ``stage='codex'`` turn.

        Batched projection used by the Board context to render the
        "codex reviewed" badge on review-column task cards (T-260). Returns
        the empty set for an empty input list to avoid a round-trip.

        Only ``stage='codex'`` turns count — opencode turns deliberately do
        NOT flip the badge (see T-260 acceptance criteria).

        ``project_id`` is required for cross-project isolation: if two
        cloglog projects happen to track the same GitHub repo / PR URL
        (supported today — ``pr_url`` uniqueness is feature-scoped, see
        the xfailed ``test_pr_url_reuse_blocked_cross_feature``), a codex
        turn persisted for project A must NOT flip the badge on project
        B's board. PR #198 round 1 codex MEDIUM finding.
        """
        ...

    async def codex_status_by_pr(
        self,
        *,
        project_id: UUID,
        pr_url_to_head_sha: dict[str, str],
        max_turns: int,
        max_pr_sessions: int,
    ) -> dict[str, CodexStatusResult]:
        """Derive a discriminated codex status for each PR in ``pr_url_to_head_sha``.

        Batched projection used by the Board context to render the
        state-aware codex badge (T-409). One round-trip per board load.

        ``pr_url_to_head_sha`` maps each PR URL to its current head SHA
        (stored in ``tasks.pr_head_sha`` by the webhook consumer on
        ``PR_SYNCHRONIZE`` / ``PR_OPENED`` events — the Review context
        does NOT fetch from GitHub). A PR whose SHA is empty string gets
        ``NOT_STARTED`` status.

        State machine (per PR, codex turns only):
        - ``NOT_STARTED`` — no turns exist for this PR at all.
        - ``WORKING``     — a turn row exists for ``head_sha`` with
                            ``status='running'``.
        - ``PASS``        — latest terminal turn for ``head_sha`` has
                            ``consensus_reached=True``.
        - ``EXHAUSTED``   — all turns for ``head_sha`` are completed
                            (``consensus_reached=False``) AND the PR-wide
                            distinct posted ``session_index`` count is
                            ≥ ``max_pr_sessions``. T-424 fix: previously
                            keyed off the per-session ``max_turns``
                            (``codex_max_turns``, default 1), which surfaced
                            EXHAUSTED on the very first non-consensus turn
                            even though ``MAX_REVIEWS_PER_PR=5`` further
                            review sessions were still permitted.
        - ``FAILED``      — latest terminal turn for ``head_sha`` has
                            ``status IN ('timed_out', 'failed')``.
        - ``PROGRESS``    — some completed turns, no consensus, count < max_turns.
        - ``STALE``       — no turns for ``head_sha`` but earlier SHAs did
                            have turns (push landed, no pickup) AND the
                            PR-wide posted-session count is still below
                            ``max_pr_sessions``. T-424 round 2: when the
                            cap is consumed on an earlier SHA and the
                            author then pushes a new SHA, the projection
                            returns EXHAUSTED instead of STALE — the
                            review loop refuses further codex sessions
                            for that PR, so a retriable-looking STALE
                            badge would mislead operators.

        ``project_id`` is required for cross-project isolation (same
        reasoning as ``codex_touched_pr_urls``).
        """
        ...
