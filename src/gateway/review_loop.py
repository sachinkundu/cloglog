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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Protocol
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
    parse_reviewer_output,
    post_review,
)
from src.review.interfaces import IReviewTurnRegistry, ReviewTurnSnapshot
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
    ) -> tuple[ReviewResult | None, float, bool]:
        """Run one turn.

        Returns ``(result, elapsed_seconds, timed_out)``. ``result`` is None on
        failure (parse error, crash) or timeout (``timed_out=True``). The loop
        maps these to ``PrReviewTurnStatus`` values.
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

    async def run(self, *, diff: str) -> LoopOutcome:
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

        async with httpx.AsyncClient() as http:
            for turn in range(start_turn, self._max_turns + 1):
                claimed = await self._registry.claim_turn(
                    project_id=self._project_id,
                    pr_url=self._pr_url,
                    pr_number=self._pr_number,
                    head_sha=self._head_sha,
                    stage=self._stage,
                    turn_number=turn,
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
                )

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
                    outcome.turns_used = turn
                    outcome.errors.append(f"turn {turn}: {status}")
                    # A failed turn doesn't short-circuit — try the next turn.
                    # Unless we've exhausted the budget; the for-loop bound takes
                    # care of that.
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

    async def run(
        self,
        *,
        diff: str,
        pr_number: int,
        turn: int,
        max_turns: int,
    ) -> tuple[ReviewResult | None, float, bool]:
        del turn, max_turns  # codex prompt is turn-agnostic; header is added by loop
        prompt = _load_project_prompt(self._project_root)
        schema_path = _get_schema_path(self._project_root)
        full_prompt = f"{prompt}\n\nDIFF:\n{diff}"

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
            start = time.monotonic()
            try:
                stdout, _stderr = await asyncio.wait_for(
                    proc.communicate(input=full_prompt.encode()),
                    timeout=REVIEW_TIMEOUT_SECONDS,
                )
                elapsed = time.monotonic() - start
            except TimeoutError:
                elapsed = time.monotonic() - start
                await _drain_stderr_after_timeout(proc)
                proc.kill()
                with contextlib.suppress(ProcessLookupError):
                    await proc.wait()
                logger.warning("codex turn timeout after %.1fs (pr=%d)", elapsed, pr_number)
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
    ) -> tuple[ReviewResult | None, float, bool]:
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
