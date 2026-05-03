"""Shared iterative-review loop for the two-stage PR review sequencer (T-248).

The sequencer in ``review_engine.py`` runs ``ReviewLoop(opencode_reviewer, 5)``
followed by ``ReviewLoop(codex_reviewer, 2)`` per PR webhook. This module
owns:

- the ``Reviewer`` protocol both adapters satisfy;
- the consensus predicate (spec §1.1 option (c), explicit flag OR empty-diff
  across the union of all prior turns);
- the turn-accounting handshake against ``IReviewTurnRegistry``;
- the per-turn GitHub review POST and the review-body header that tags the
  reviewer, model, and cross-session counter
  (``**codex (Claude 4.x) — session 2/5**``). The intra-session turn index
  is an implementation detail not exposed in the body — readers only act on
  the session counter (T-227 approval-based stop + 5-session backstop).

Keeping the loop in its own module keeps ``review_engine.py``'s
``ReviewEngineConsumer`` focused on webhook plumbing and lets real-DB tests
exercise the loop with an in-memory ``IReviewTurnRegistry`` stub.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import tempfile
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Protocol
from uuid import UUID

import httpx

from src.gateway.review_engine import (
    REVIEW_TIMEOUT_SECONDS,
    ReviewResult,
    _create_subprocess,
    _drain_stderr_after_timeout,
    _get_schema_path,
    _load_project_prompt,
    _tail_excerpt,
    compute_review_timeout,
    parse_reviewer_output,
    post_review,
)
from src.review.interfaces import (
    IReviewTurnRegistry,
    PriorContext,
    PriorTurnSummary,
    ReviewTurnSnapshot,
)
from src.shared.config import settings
from src.shared.events import Event, EventType, event_bus

logger = logging.getLogger(__name__)

_OPENCODE_PROMPT_PATH = Path(".github/opencode/prompts/review.md")

# Per-turn status strings — match the CHECK constraint in
# src/review/models.py :: PrReviewTurnStatus so the registry does not need to
# import this module (no circular edge across contexts).
_TURN_STATUS_COMPLETED = "completed"
_TURN_STATUS_TIMED_OUT = "timed_out"
_TURN_STATUS_FAILED = "failed"


# T-377: signature for the codex-finalization → CI dispatch hook. Defined as a
# Callable so tests can inject a fake dispatcher without monkey-patching httpx
# or token plumbing. Called exactly once per (pr_url, head_sha) when stage B
# reaches a terminal state — either consensus or codex_max_turns exhausted.
CIDispatcher = Callable[..., Awaitable[None]]


async def dispatch_ci_after_codex(
    *,
    repo_full_name: str,
    head_sha: str,
    pr_number: int,
) -> None:
    """Trigger CI on (repo, head_sha) via the ``codex-finalized`` repository_dispatch.

    Issued once stage B reaches a terminal state — consensus or
    codex_max_turns exhausted. ci.yml's ``repository_dispatch:
    types: [codex-finalized]`` trigger checks out ``client_payload.head_sha``
    and runs the full suite against the SHA the reviewer signed off on (or
    gave up on). See docs/design/ci-codex-trigger.md for the full flow.

    Permissions: uses the Claude bot token (``contents: write``) — the
    codex-reviewer App is intentionally read-only and lacks the
    ``contents:write`` permission that the dispatches endpoint requires.

    Failure is logged but does not raise — a missed dispatch surfaces as a
    PR with no CI signal post-finalization, which the operator can recover
    by re-pushing or by manually re-issuing the dispatch.
    """
    from src.gateway.github_token import get_github_app_token

    token = await get_github_app_token()
    url = f"https://api.github.com/repos/{repo_full_name}/dispatches"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {
        "event_type": "codex-finalized",
        "client_payload": {
            "head_sha": head_sha,
            "pr_number": pr_number,
        },
    }
    try:
        async with httpx.AsyncClient() as http:
            resp = await http.post(url, headers=headers, json=payload, timeout=10.0)
            resp.raise_for_status()
        logger.info(
            "ci_dispatch_codex_finalized pr=%d sha=%s repo=%s",
            pr_number,
            head_sha[:7],
            repo_full_name,
        )
    except (httpx.HTTPError, httpx.HTTPStatusError) as err:
        logger.error(
            "ci_dispatch_failed pr=%d sha=%s repo=%s err=%s",
            pr_number,
            head_sha[:7],
            repo_full_name,
            err,
        )


class Reviewer(Protocol):
    """One iteration of one reviewer (opencode or codex).

    ``run`` receives the current PR diff and the turn label, spawns the
    reviewer subprocess, and returns a ``ReviewResult`` or ``None``. The loop
    handles everything else (turn claim, posting, consensus).
    """

    bot_username: str
    display_label: str  # e.g., "opencode (gemma4:e4b)" — appears in review body header

    async def run(
        self,
        *,
        diff: str,
        pr_number: int,
        turn: int,
        max_turns: int,
        prior_context: PriorContext | None = None,
        pr_body: str | None = None,
    ) -> tuple[ReviewResult | None, float, bool]:
        """Run one turn.

        Returns ``(result, elapsed_seconds, timed_out)``. ``result`` is None on
        failure (parse error, crash) or timeout (``timed_out=True``). The loop
        maps these to ``PrReviewTurnStatus`` values.

        ``prior_context`` carries findings + learnings from earlier turns of
        this stage on this PR (T-367 cross-push memory). Implementations may
        ignore it — opencode does today; codex renders it as a prompt
        preamble. ``pr_body`` is the raw PR description (the
        ``.github/pull_request_template.md`` sections an agent filled);
        codex injects it under "What this PR is doing" so the reviewer has
        the human-equivalent context.
        """
        ...


@dataclass
class LoopOutcome:
    """Terminal state of one ``ReviewLoop.run`` call."""

    turns_used: int
    consensus_reached: bool
    total_elapsed_seconds: float
    reviewer_unavailable: bool = False
    errors: list[str] = field(default_factory=list)
    # T-374 — diagnostics from the most recent codex turn that returned
    # ``timed_out=True``. ``ReviewEngineConsumer._review_pr`` reads these
    # to post the AGENT_TIMEOUT skip comment, mirroring the legacy
    # ``_run_review_agent`` finalization. ``last_timed_out`` is the
    # gating flag — diagnostic fields are only meaningful when it is
    # True. Opencode timeouts deliberately do not populate these fields.
    last_timed_out: bool = False
    last_timeout_diff_lines: int = 0
    last_timeout_seconds: float = 0.0
    last_timeout_stderr_excerpt: str = ""
    last_timeout_elapsed_seconds: float = 0.0


def _finding_key(finding: dict[str, object] | object) -> tuple[str, int, str]:
    """Stable tuple for consensus predicate (b) — ``(file, line, title_lower)``.

    Accepts both a raw dict (Codex-schema parsed) and a ``ReviewFinding`` model
    instance — ReviewLoop calls this on ``result.findings`` which is
    ``list[ReviewFinding]``.
    """
    if isinstance(finding, dict):
        file_ = str(finding.get("file", ""))
        raw_line = finding.get("line", 0)
        try:
            line_ = int(raw_line)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            line_ = 0
        title_ = str(finding.get("title", ""))
    else:
        file_ = getattr(finding, "file", "") or ""
        line_ = int(getattr(finding, "line", 0) or 0)
        title_ = getattr(finding, "title", "") or ""
    return (file_, line_, title_.strip().lower())


_SEVERE_SEVERITIES: Final = frozenset({"critical", "high"})


def _render_pr_body_section(pr_body: str | None) -> str:
    """Render the "What this PR is doing" preamble section for codex.

    ``pr_body`` is the raw PR description authored by Claude (or the human).
    Empty body or all-whitespace body collapses to a one-line "no PR
    description provided" so codex can see *that* fact rather than silently
    being given less context.
    """
    body = (pr_body or "").strip()
    if not body:
        return (
            "## What this PR is doing\n\n"
            "(The PR has no description. Reviewing diff intent unverified.)\n"
        )
    return f"## What this PR is doing\n\n{body}\n"


def _dedupe_learnings(turns: list[PriorTurnSummary]) -> list[dict[str, str]]:
    """Collapse prior-turn learnings by ``topic``, last-write-wins on ``note``.

    A topic restated across turns means codex re-emitted the same fact —
    show it once. Last-turn note wins because that is the freshest framing
    of the same fact. Stable order: first-seen-topic order.
    """
    seen: dict[str, str] = {}
    order: list[str] = []
    for turn in turns:
        for learning in turn.learnings:
            topic = str(learning.get("topic", "")).strip()
            note = str(learning.get("note", "")).strip()
            if not topic or not note:
                continue
            if topic not in seen:
                order.append(topic)
            seen[topic] = note
    return [{"topic": t, "note": seen[t]} for t in order]


def _render_prior_history_section(prior_context: PriorContext | None) -> str:
    """Render the "Prior review history" preamble, or an empty string.

    Empty when no prior turns exist — i.e., this is turn 1 of the codex
    stage on this PR. Otherwise emits dedupe'd learnings followed by every
    finding from every prior turn (oldest first), grouped by turn header so
    codex can see which commit each finding was filed against.

    Author responses to findings are not fetched here — the spec defers
    that to a follow-up. The placeholder ``Author response: (not fetched)``
    is rendered so the prompt shape is stable when the wiring lands.
    """
    if prior_context is None or not prior_context.turns:
        return ""
    lines = [
        "## Prior review history",
        "",
        (
            "You have reviewed earlier commits of this PR. Findings you raised "
            "previously and codebase facts you noted are listed below. Use the "
            'rules in the prompt\'s "Prior review history" section to decide '
            "whether to re-state, drop, or supersede each."
        ),
        "",
    ]
    deduped = _dedupe_learnings(prior_context.turns)
    if deduped:
        lines += ["### Codebase learnings from prior turns", ""]
        for item in deduped:
            lines.append(f"- **{item['topic']}** — {item['note']}")
        lines.append("")
    lines += ["### Prior findings", ""]
    for turn in prior_context.turns:
        sha7 = (turn.head_sha or "")[:7] or "unknown"
        lines.append(f"#### Turn {turn.turn_number} (commit `{sha7}`)")
        lines.append("")
        if not turn.findings:
            lines.append("(no findings filed this turn)")
            lines.append("")
            continue
        for finding in turn.findings:
            file_ = finding.get("file", "?")
            line = finding.get("line", "?")
            title = finding.get("title") or finding.get("body", "")
            severity = finding.get("severity", "info")
            body = finding.get("body", "")
            lines.append(f"- `{file_}:{line}` **[{str(severity).upper()}]** {title}")
            if body and body != title:
                lines.append(f"  - Body: {body}")
            lines.append("  - Author response: (not fetched)")
        lines.append("")
    return "\n".join(lines) + "\n"


def build_codex_prompt(
    *,
    base_prompt: str,
    pr_body: str | None,
    prior_context: PriorContext | None,
    diff: str,
) -> str:
    """Assemble the final codex prompt: base + PR body + prior history + diff.

    Pulled out of ``CodexReviewer.run`` so tests can pin the exact rendered
    shape without spawning a subprocess.
    """
    parts = [base_prompt, _render_pr_body_section(pr_body)]
    history = _render_prior_history_section(prior_context)
    if history:
        parts.append(history)
    parts.append(f"DIFF:\n{diff}")
    return "\n\n".join(parts)


def _reached_consensus(
    *,
    result: ReviewResult,
    prior_finding_keys: set[tuple[str, int, str]],
) -> bool:
    """Three independent short-circuit predicates; any one fires.

    (a) Explicit ``status == "no_further_concerns"`` flag.
    (b) ``verdict == "approve"`` ("patch is correct" in the codex schema),
        BUT only when the same review carries no ``critical``/``high``
        findings. A model that marks the patch "correct" while listing a
        critical or high issue has contradicted itself — short-circuiting
        there would skip the codex stage and ship the contradiction.
        Observed on PR #190 (2026-04-23) with gemma4-e4b-32k emitting
        ``:pass:`` + ``[CRITICAL]`` in the same turn. Defensive: fall
        through to predicate (c) in that case.
    (c) No new findings vs. all prior turns' finding keys.
    """
    if result.status == "no_further_concerns":
        return True
    if result.verdict == "approve" and not any(
        getattr(f, "severity", None) in _SEVERE_SEVERITIES for f in result.findings
    ):
        return True
    current_keys = {_finding_key(f) for f in result.findings}
    return len(current_keys - prior_finding_keys) == 0


class ReviewLoop:
    """Iterate a ``Reviewer`` until consensus or ``max_turns`` — per stage."""

    def __init__(
        self,
        reviewer: Reviewer,
        *,
        max_turns: int,
        registry: IReviewTurnRegistry,
        project_id: UUID,
        pr_url: str,
        pr_number: int,
        repo_full_name: str,
        head_sha: str,
        stage: str,
        reviewer_token: str,
        session_index: int,
        max_sessions: int,
        session_factory: Any | None = None,
        head_branch: str = "",
        ci_dispatcher: CIDispatcher | None = None,
    ) -> None:
        self._reviewer = reviewer
        self._max_turns = max_turns
        self._registry = registry
        self._project_id = project_id
        self._pr_url = pr_url
        self._pr_number = pr_number
        self._repo_full_name = repo_full_name
        self._head_sha = head_sha
        self._stage = stage
        self._token = reviewer_token
        self._session_index = session_index
        self._max_sessions = max_sessions
        self._session_factory = session_factory
        # T-374 (codex round 1 CRITICAL): the secondary recipient lookup in
        # ``AgentNotifierConsumer._resolve_agent`` falls back to branch name
        # when ``Task.pr_url`` has not been bound yet. Without ``head_branch``
        # the synthesised webhook event in the timeout emitter skips that
        # branch lookup and lands in the main-agent inbox or is dropped —
        # contradicting the routing-parity contract documented on the event.
        self._head_branch = head_branch
        # T-377: only the codex stage triggers CI; opencode (stage A) is
        # advisory and never gates merge. Callers wire this for codex only.
        self._ci_dispatcher = ci_dispatcher

    @staticmethod
    def _build_body_header(reviewer: Reviewer, session_index: int, max_sessions: int) -> str:
        """Per-session review-body header.

        Example: ``**codex (Claude 4.x) — session 2/5**``. Always the first
        line of the review summary. The counter is cross-session (T-227
        approval-based stop + 5-session backstop): every webhook firing
        starts a fresh session, so a reader needs to see which of the five
        per-PR sessions they are looking at. The intra-session turn index
        (``opencode_max_turns``/``codex_max_turns``) is an implementation
        detail no reader acts on and is deliberately not shown.
        """
        return f"**{reviewer.display_label} — session {session_index}/{max_sessions}**"

    async def run(
        self,
        *,
        diff: str,
        prior_context: PriorContext | None = None,
        pr_body: str | None = None,
    ) -> LoopOutcome:
        start_all = time.monotonic()
        prior_keys: set[tuple[str, int, str]] = set()
        # Hydrate prior keys from already-persisted turns for this (pr, sha).
        # Idempotency (spec §3.3) keeps this list consistent across webhook
        # re-fires — a claim_turn that returns False means another handler is
        # already running the same turn.
        existing = await self._registry.turns_for_stage(
            pr_url=self._pr_url, head_sha=self._head_sha, stage=self._stage
        )
        outcome = LoopOutcome(turns_used=0, consensus_reached=False, total_elapsed_seconds=0.0)

        # Spec §3.3 + PR #187 round 2 HIGH: if ANY prior turn on this
        # (pr_url, head_sha, stage) already recorded consensus_reached=True,
        # the stage is terminal for this SHA. A webhook redelivery must not
        # post another review on the same commit — short-circuit here before
        # claim_turn advances past the completed work.
        if any(t.consensus_reached for t in existing):
            prior_consensus_turn = max(t.turn_number for t in existing if t.consensus_reached)
            logger.info(
                "review_stage_already_at_consensus stage=%s pr=%d sha=%s turn=%d — noop",
                self._stage,
                self._pr_number,
                self._head_sha[:7],
                prior_consensus_turn,
            )
            outcome.turns_used = prior_consensus_turn
            outcome.consensus_reached = True
            outcome.total_elapsed_seconds = time.monotonic() - start_all
            return outcome

        start_turn = self._compute_next_turn(existing)
        if start_turn > self._max_turns:
            # Already ran to cap on a prior webhook delivery — nothing to do.
            outcome.total_elapsed_seconds = time.monotonic() - start_all
            return outcome

        # T-375 at-most-once-per-session short-circuit. A session may have
        # already posted on a prior webhook delivery for this same SHA (the
        # loop wrote ``posted_at`` in the prior run). The partial unique
        # index ``uq_pr_review_turns_one_post_per_session`` would reject a
        # second ``mark_posted`` for this (pr_url, stage, session_index)
        # anyway, but exiting in-process here saves a GitHub round-trip and
        # avoids confusing the contributor with a near-duplicate review body.
        #
        # Detection is generous on purpose:
        # 1. ``posted_at`` is stamped and ``session_index`` matches —
        #    authoritative T-375 signal.
        # 2. Pre-T-375 fallback: a row with ``session_index IS NULL`` that
        #    nonetheless reached ``status='completed'`` with a non-null
        #    ``finding_count`` was, under the prior code path, a successful
        #    POST. Same head_sha implies same session by construction
        #    (session_index = ``count_bot_reviews + 1``, which is constant
        #    for a given head_sha because ``count_bot_reviews`` collapses by
        #    ``commit_id``). Treating these as posted closes the upgrade
        #    window where a webhook re-fire after T-375 deploys could
        #    otherwise re-post under the same session counter on a
        #    historical row.
        if any(
            (row.posted_at is not None and row.session_index == self._session_index)
            or (
                row.session_index is None
                and row.status == _TURN_STATUS_COMPLETED
                and row.finding_count is not None
            )
            for row in existing
        ):
            posted_turn = max(
                (
                    row.turn_number
                    for row in existing
                    if row.posted_at is not None or row.status == _TURN_STATUS_COMPLETED
                ),
                default=0,
            )
            logger.info(
                "review_session_already_posted stage=%s pr=%d sha=%s session=%d/%d "
                "posted_turn=%d — short-circuit",
                self._stage,
                self._pr_number,
                self._head_sha[:7],
                self._session_index,
                self._max_sessions,
                posted_turn,
            )
            outcome.turns_used = posted_turn
            outcome.total_elapsed_seconds = time.monotonic() - start_all
            return outcome

        # T-375: tracks whether this run has already posted to GitHub. Set
        # to True after a successful ``post_review`` + ``mark_posted``;
        # subsequent for-loop iterations within this same call (only
        # possible when ``codex_max_turns > 1``) suppress the POST. The
        # cross-fire case is handled by the early-return short-circuit
        # above; this flag handles intra-run multi-turn refinement.
        session_already_posted = False
        async with httpx.AsyncClient() as http:
            for turn in range(start_turn, self._max_turns + 1):
                claimed = await self._registry.claim_turn(
                    project_id=self._project_id,
                    pr_url=self._pr_url,
                    pr_number=self._pr_number,
                    head_sha=self._head_sha,
                    stage=self._stage,
                    turn_number=turn,
                    session_index=self._session_index,
                )
                if not claimed:
                    # A prior POST-failed turn leaves a ``failed`` row that
                    # blocks the ON CONFLICT DO NOTHING insert. Try to flip
                    # it back to ``running`` — if that succeeds we own the
                    # retry. Otherwise another handler is actively running
                    # this turn; give up cleanly (spec §3.3 idempotency +
                    # PR #187 round 1 HIGH-3 fix).
                    reset_ok = await self._registry.reset_to_running(
                        pr_url=self._pr_url,
                        head_sha=self._head_sha,
                        stage=self._stage,
                        turn_number=turn,
                    )
                    if not reset_ok:
                        logger.info(
                            "review_turn_skipped_already_claimed stage=%s turn=%d pr=%d sha=%s",
                            self._stage,
                            turn,
                            self._pr_number,
                            self._head_sha[:7],
                        )
                        break

                logger.info(
                    "review_turn_start stage=%s turn=%d/%d pr=%d sha=%s",
                    self._stage,
                    turn,
                    self._max_turns,
                    self._pr_number,
                    self._head_sha[:7],
                )

                # T-260: the dashboard's "codex reviewed" badge is driven by
                # a boolean projection from ``pr_review_turns``. Publish an
                # SSE event every time we enter a codex turn so the frontend
                # re-fetches the board and the badge appears as soon as
                # stage B is engaged. Opencode turns deliberately do not
                # emit — only codex flips the badge.
                if self._stage == "codex":
                    await event_bus.publish(
                        Event(
                            type=EventType.REVIEW_CODEX_TURN_STARTED,
                            project_id=self._project_id,
                            data={
                                "pr_url": self._pr_url,
                                "pr_number": self._pr_number,
                                "head_sha": self._head_sha,
                                "turn_number": turn,
                            },
                        )
                    )

                result, elapsed, timed_out = await self._reviewer.run(
                    diff=diff,
                    pr_number=self._pr_number,
                    turn=turn,
                    max_turns=self._max_turns,
                    prior_context=prior_context,
                    pr_body=pr_body,
                )

                # T-374 codex round 2 HIGH: ``last_timed_out`` (and the
                # related ``last_timeout_*`` diagnostics) must reflect the
                # *terminal* state of the codex stage, not "some prior turn
                # timed out". Reset on each iteration; the timeout branch
                # below re-sets them only for this turn. A subsequent
                # successful turn will not re-enter this block, and the
                # per-iteration reset stops a stale ``True`` from leaking
                # past the loop. Only diagnostics — ``errors`` is the
                # cumulative log and stays as-is.
                outcome.last_timed_out = False
                outcome.last_timeout_diff_lines = 0
                outcome.last_timeout_seconds = 0.0
                outcome.last_timeout_stderr_excerpt = ""
                outcome.last_timeout_elapsed_seconds = 0.0

                if result is None:
                    status = _TURN_STATUS_TIMED_OUT if timed_out else _TURN_STATUS_FAILED
                    await self._registry.complete_turn(
                        pr_url=self._pr_url,
                        head_sha=self._head_sha,
                        stage=self._stage,
                        turn_number=turn,
                        status=status,
                        finding_count=None,
                        consensus_reached=False,
                        elapsed_seconds=elapsed,
                    )
                    if timed_out and self._stage == "codex":
                        # T-374 (codex round 5 HIGH): record the timeout
                        # diagnostics on the outcome only — do NOT emit the
                        # supervisor event from inside the per-turn branch.
                        # ``ReviewLoop.run`` is allowed to continue after a
                        # timed-out turn (`docs/design/two-stage-pr-review.md`),
                        # so a per-turn emit would falsely tell the
                        # supervisor about a non-terminal timeout if a
                        # subsequent turn succeeds. Terminal-state
                        # emission lives in
                        # ``ReviewEngineConsumer._review_pr`` after the
                        # loop returns and ``last_timed_out`` is read.
                        diff_lines = getattr(self._reviewer, "_last_diff_lines", 0)
                        budget = getattr(
                            self._reviewer, "_last_timeout_seconds", REVIEW_TIMEOUT_SECONDS
                        )
                        stderr_excerpt = getattr(self._reviewer, "_last_stderr_excerpt", "")
                        outcome.last_timed_out = True
                        outcome.last_timeout_diff_lines = diff_lines
                        outcome.last_timeout_seconds = budget
                        outcome.last_timeout_stderr_excerpt = stderr_excerpt
                        outcome.last_timeout_elapsed_seconds = elapsed
                    outcome.turns_used = turn
                    outcome.errors.append(f"turn {turn}: {status}")
                    # A failed turn doesn't short-circuit — try the next turn.
                    # Unless we've exhausted the budget; the for-loop bound takes
                    # care of that.
                    continue

                # T-375 at-most-once-per-session guard. If a prior turn in
                # this same logical session (same session_index, regardless
                # of turn_number) already posted, suppress this POST. The
                # turn still records as ``completed`` with the reviewer's
                # finding count so cross-push memory replays correctly; the
                # ``posted_at`` column stays NULL on this row, and the next
                # session (different session_index) is unaffected.
                if session_already_posted:
                    consensus = _reached_consensus(result=result, prior_finding_keys=prior_keys)
                    logger.info(
                        "review_post_suppressed_already_posted_this_session "
                        "stage=%s turn=%d pr=%d sha=%s session=%d/%d "
                        "consensus=%s — completing turn without re-posting",
                        self._stage,
                        turn,
                        self._pr_number,
                        self._head_sha[:7],
                        self._session_index,
                        self._max_sessions,
                        consensus,
                    )
                    await self._registry.complete_turn(
                        pr_url=self._pr_url,
                        head_sha=self._head_sha,
                        stage=self._stage,
                        turn_number=turn,
                        status=_TURN_STATUS_COMPLETED,
                        finding_count=len(result.findings),
                        consensus_reached=consensus,
                        elapsed_seconds=elapsed,
                    )
                    await self._registry.record_findings_and_learnings(
                        pr_url=self._pr_url,
                        head_sha=self._head_sha,
                        stage=self._stage,
                        turn_number=turn,
                        findings_json=[f.model_dump() for f in result.findings],
                        learnings_json=list(result.learnings),
                    )
                    outcome.turns_used = turn
                    prior_keys.update(_finding_key(f) for f in result.findings)
                    if consensus:
                        # Suppress further POSTs but signal terminal state
                        # so the consumer's CI dispatch + finalizer fire.
                        outcome.consensus_reached = True
                        break
                    # No consensus yet — let cross-push memory aggregate
                    # but the for-loop bound caps us; no more POSTs will
                    # happen this session.
                    continue

                # Prepend the per-session header to the review summary so the
                # GitHub review body shows `**<bot> — session N/M**` at the top.
                header = self._build_body_header(
                    self._reviewer, self._session_index, self._max_sessions
                )
                annotated = ReviewResult(
                    verdict=result.verdict,
                    summary=f"{header}\n\n{result.summary}",
                    findings=result.findings,
                    status=result.status,
                )

                posted = await post_review(
                    self._repo_full_name,
                    self._pr_number,
                    annotated,
                    diff,
                    self._token,
                    head_sha=self._head_sha,
                    client=http,
                )
                if not posted:
                    # GitHub POST failed twice (``post_review`` retries once
                    # internally). Mark the turn ``failed`` so a webhook
                    # re-fire can reset it back to running and retry — without
                    # this, turn accounting advances past the missing comment
                    # and the author never sees these findings (PR #187
                    # round 1 HIGH-3 fix).
                    logger.warning(
                        "review_turn_post_failed stage=%s turn=%d pr=%d — "
                        "marked failed; webhook re-fire will retry",
                        self._stage,
                        turn,
                        self._pr_number,
                    )
                    await self._registry.complete_turn(
                        pr_url=self._pr_url,
                        head_sha=self._head_sha,
                        stage=self._stage,
                        turn_number=turn,
                        status=_TURN_STATUS_FAILED,
                        finding_count=len(result.findings),
                        consensus_reached=False,
                        elapsed_seconds=elapsed,
                    )
                    outcome.turns_used = turn
                    outcome.errors.append(f"turn {turn}: post_failed")
                    break

                consensus = _reached_consensus(result=result, prior_finding_keys=prior_keys)
                await self._registry.complete_turn(
                    pr_url=self._pr_url,
                    head_sha=self._head_sha,
                    stage=self._stage,
                    turn_number=turn,
                    status=_TURN_STATUS_COMPLETED,
                    finding_count=len(result.findings),
                    consensus_reached=consensus,
                    elapsed_seconds=elapsed,
                )
                # T-375: stamp ``posted_at`` so a subsequent webhook re-fire
                # for the same SHA detects this session has already posted
                # and short-circuits via ``session_already_posted``. The
                # partial unique index also rejects any future ``mark_posted``
                # for the same (pr_url, stage, session_index) at the DB
                # layer — a defense-in-depth safety net under the in-process
                # guard. ``mark_posted`` returning False here means the
                # registry refused (race / constraint hit); we log and
                # continue — the GitHub POST already happened, no recovery.
                marked = await self._registry.mark_posted(
                    pr_url=self._pr_url,
                    head_sha=self._head_sha,
                    stage=self._stage,
                    turn_number=turn,
                )
                if not marked:
                    logger.warning(
                        "review_mark_posted_rejected stage=%s turn=%d pr=%d "
                        "session=%d/%d — partial unique index hit or row missing",
                        self._stage,
                        turn,
                        self._pr_number,
                        self._session_index,
                        self._max_sessions,
                    )
                session_already_posted = True
                # T-367 cross-push memory: persist the findings + learnings on
                # the same row complete_turn just updated, so the next turn's
                # prompt can replay them. Only meaningful for codex
                # (opencode emits no learnings and the codex stage's preamble
                # is the only consumer); harmless to write on opencode rows
                # too — learnings will be empty.
                await self._registry.record_findings_and_learnings(
                    pr_url=self._pr_url,
                    head_sha=self._head_sha,
                    stage=self._stage,
                    turn_number=turn,
                    findings_json=[f.model_dump() for f in result.findings],
                    learnings_json=list(result.learnings),
                )
                logger.info(
                    "review_turn_end stage=%s turn=%d/%d pr=%d findings=%d "
                    "consensus=%s elapsed=%.1fs",
                    self._stage,
                    turn,
                    self._max_turns,
                    self._pr_number,
                    len(result.findings),
                    consensus,
                    elapsed,
                )
                outcome.turns_used = turn
                # Merge this turn's keys into the running set for the NEXT
                # turn's predicate (b) check.
                prior_keys.update(_finding_key(f) for f in result.findings)
                if consensus:
                    outcome.consensus_reached = True
                    break

        outcome.total_elapsed_seconds = time.monotonic() - start_all
        logger.info(
            "review_stage_end stage=%s pr=%d turns=%d consensus=%s elapsed=%.1fs",
            self._stage,
            self._pr_number,
            outcome.turns_used,
            outcome.consensus_reached,
            outcome.total_elapsed_seconds,
        )

        # T-377: codex finalization → CI dispatch hook. Fired once per
        # (PR, head_sha) when stage B is terminal: either consensus reached
        # or all max_turns ran with no retryable-on-re-fire failure on any
        # turn. ``_compute_next_turn`` (line 581-583) resumes the lowest
        # ``status=='failed'`` row on a webhook re-fire, and BOTH the
        # subprocess-crash path (`result is None and timed_out=False` →
        # status=failed) and the GitHub-POST-failed path (status=failed,
        # outcome.errors carries "post_failed") are retryable. Dispatching
        # then would let CI race a review the system still considers
        # rerunnable. ``timed_out`` is NOT retryable (status=='timed_out',
        # not failed) so an exhausted stage whose tail-end timed out still
        # dispatches. The early-return paths above (lines 351 / 366) skip
        # this entirely — those are webhook re-fires for an already-
        # finalized stage; the original firing already dispatched.
        retryable_failure = any(
            err.endswith(": failed") or "post_failed" in err for err in outcome.errors
        )
        if (
            self._stage == "codex"
            and self._ci_dispatcher is not None
            and (
                outcome.consensus_reached
                or (outcome.turns_used == self._max_turns and not retryable_failure)
            )
        ):
            try:
                await self._ci_dispatcher(
                    repo_full_name=self._repo_full_name,
                    head_sha=self._head_sha,
                    pr_number=self._pr_number,
                )
            except Exception as err:  # pragma: no cover — defensive
                logger.warning(
                    "ci_dispatch_hook_raised pr=%d sha=%s err=%s",
                    self._pr_number,
                    self._head_sha[:7],
                    err,
                )

        return outcome

    @staticmethod
    def _compute_next_turn(existing: list[ReviewTurnSnapshot]) -> int:
        """Turn number to resume at on this ``(pr_url, head_sha, stage)``.

        Resolution order:

        1. No prior rows → start at turn 1.
        2. Any prior row with ``status='failed'`` (e.g. a previous GitHub
           POST failure) → resume at the **lowest** failed turn so the loop
           can retry it via ``reset_to_running``. Without this, post-failed
           turns were advanced past and the author never saw those findings
           (PR #187 round 1 HIGH-3).
        3. Otherwise → ``max(turn_number) + 1`` (next unused turn).
        """
        if not existing:
            return 1
        failed = sorted(t.turn_number for t in existing if t.status == "failed")
        if failed:
            return failed[0]
        return max(t.turn_number for t in existing) + 1


# ---------------------------------------------------------------------------
# Reviewer adapters — satisfy the ``Reviewer`` protocol for codex and opencode.
# Each owns its own subprocess invocation shape; the loop is agnostic.
# ---------------------------------------------------------------------------


class CodexReviewer:
    """Wraps the existing codex CLI subprocess call (F-36 path)."""

    bot_username = "cloglog-codex-reviewer[bot]"
    display_label = "codex"

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root
        # Surfaced for the ReviewLoop's timeout-event emitter — the inbox
        # event needs both the diff size that drove the budget and the
        # budget itself. Reset on every ``run`` call so a sequence of turns
        # reports the latest call's values.
        self._last_diff_lines: int = 0
        self._last_timeout_seconds: float = REVIEW_TIMEOUT_SECONDS
        # Surfaced so the sequenced path can format the AGENT_TIMEOUT skip
        # comment with the same stderr-tail UX the legacy path emits.
        self._last_stderr_excerpt: str = ""

    async def run(
        self,
        *,
        diff: str,
        pr_number: int,
        turn: int,
        max_turns: int,
        prior_context: PriorContext | None = None,
        pr_body: str | None = None,
    ) -> tuple[ReviewResult | None, float, bool]:
        del turn, max_turns  # codex prompt is turn-agnostic; header is added by loop
        prompt = _load_project_prompt(self._project_root)
        schema_path = _get_schema_path(self._project_root)
        full_prompt = build_codex_prompt(
            base_prompt=prompt,
            pr_body=pr_body,
            prior_context=prior_context,
            diff=diff,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "review.json"
            args = [
                settings.review_agent_cmd,
                "exec",
                "--dangerously-bypass-approvals-and-sandbox",
                "--ephemeral",
                "--color",
                "never",
                "-o",
                str(output_path),
                "-C",
                str(self._project_root),
            ]
            if schema_path is not None:
                args += ["--output-schema", str(schema_path)]
            args.append("-")

            proc = await _create_subprocess(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._project_root),
            )
            self._last_diff_lines, timeout_seconds = compute_review_timeout(diff)
            self._last_timeout_seconds = timeout_seconds
            self._last_stderr_excerpt = ""
            start = time.monotonic()
            try:
                stdout, _stderr = await asyncio.wait_for(
                    proc.communicate(input=full_prompt.encode()),
                    timeout=timeout_seconds,
                )
                elapsed = time.monotonic() - start
            except TimeoutError:
                elapsed = time.monotonic() - start
                captured = await _drain_stderr_after_timeout(proc)
                self._last_stderr_excerpt = _tail_excerpt(captured)
                proc.kill()
                with contextlib.suppress(ProcessLookupError):
                    await proc.wait()
                logger.warning(
                    "codex turn timeout after %.1fs (pr=%d, diff_lines=%d, budget=%.0fs)",
                    elapsed,
                    pr_number,
                    self._last_diff_lines,
                    timeout_seconds,
                )
                return (None, elapsed, True)

            if output_path.exists():
                raw = output_path.read_text()
                parsed = parse_reviewer_output(raw, pr_number)
                if parsed is not None:
                    return (parsed, elapsed, False)
            if stdout:
                parsed = parse_reviewer_output(stdout.decode(errors="replace"), pr_number)
                if parsed is not None:
                    return (parsed, elapsed, False)
            return (None, elapsed, False)


class OpencodeReviewer:
    """Wraps the local opencode CLI (stage A of T-248)."""

    bot_username = "cloglog-opencode-reviewer[bot]"

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root
        self.display_label = f"opencode ({settings.opencode_model})"

    @staticmethod
    def _load_prompt(project_root: Path) -> str:
        path = project_root / _OPENCODE_PROMPT_PATH
        if path.exists():
            return path.read_text()
        # Fallback to the codex prompt if opencode prompt is missing; better to
        # run SOMETHING than to fail silently.
        return _load_project_prompt(project_root)

    def _build_args(self, full_prompt: str) -> list[str]:
        # T-272 hotfix: `--pure` means "no external plugins" — it gates the
        # default agentic plugin set that otherwise gives the model tool
        # access. Without it, gemma4-e4b-32k narrates tool calls ("calling
        # multiple tools to gather context...") instead of emitting the
        # review JSON, parse_reviewer_output fails, and every PR since
        # T-268 landed has had zero opencode coverage. Restoring `--pure`
        # forces single-shot text emission.
        return [
            settings.opencode_cmd,
            "run",
            "--model",
            settings.opencode_model,
            "--log-level",
            "ERROR",
            "--pure",
            "--dangerously-skip-permissions",
            "--dir",
            str(self._project_root),
            "--",
            full_prompt,
        ]

    async def run(
        self,
        *,
        diff: str,
        pr_number: int,
        turn: int,
        max_turns: int,
        prior_context: PriorContext | None = None,
        pr_body: str | None = None,
    ) -> tuple[ReviewResult | None, float, bool]:
        del prior_context, pr_body  # opencode runs without cross-push memory (T-367 §2)
        prompt = self._load_prompt(self._project_root)
        full_prompt = f"{prompt}\n\nCurrent turn: {turn}/{max_turns}.\n\nDIFF:\n{diff}"
        args = self._build_args(full_prompt)
        proc = await _create_subprocess(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self._project_root),
        )
        start = time.monotonic()
        timeout = settings.opencode_turn_timeout_seconds
        try:
            stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            elapsed = time.monotonic() - start
        except TimeoutError:
            elapsed = time.monotonic() - start
            await _drain_stderr_after_timeout(proc)
            proc.kill()
            with contextlib.suppress(ProcessLookupError):
                await proc.wait()
            logger.warning("opencode turn timeout after %.1fs (pr=%d)", elapsed, pr_number)
            return (None, elapsed, True)

        parsed = parse_reviewer_output(stdout.decode(errors="replace"), pr_number)
        if parsed is None:
            # Best-effort diagnostics: log the first JSON-ish fragment that
            # failed to parse, not the whole stdout (can be large).
            excerpt = _tail_excerpt(stdout)
            logger.warning(
                "opencode output unparseable (pr=%d, %d bytes, tail=%r)",
                pr_number,
                len(stdout),
                excerpt[:120],
            )
            return (None, elapsed, False)
        return (parsed, elapsed, False)
