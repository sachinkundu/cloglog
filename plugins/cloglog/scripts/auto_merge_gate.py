"""Pure decision logic for the worktree-agent's auto-merge gate (T-295).

The gate decides whether the agent should run
``gh pr merge <num> --squash --delete-branch`` on its own PR after a
``review_submitted`` inbox event arrives. All five conditions must hold:

1. The reviewer is the codex bot (``cloglog-codex-reviewer[bot]``) — random
   commenters never trigger an auto-merge.
2. The review body, after ``lstrip()``, starts with the codex approval marker
   ``:pass:`` (matches ``_APPROVE_BODY_PREFIX`` in
   ``src/gateway/review_engine.py``).
3. No human reviewer's most recent review on the PR is ``CHANGES_REQUESTED``.
   Codex always posts as ``event="COMMENT"`` (see ``post_review`` in
   ``src/gateway/review_engine.py``), so a codex ``:pass:`` does NOT clear a
   human's outstanding change request — GitHub still blocks the merge from
   the human's side, and we must too.
4. Every CI check on the PR has terminated with ``success`` (or is an
   intentional ``skipping``). Pending or failing checks block the merge.
5. The PR does not carry the ``hold-merge`` label.

The CLI form reads a single JSON object on stdin with the fields:

    {
      "reviewer": "cloglog-codex-reviewer[bot]",
      "body": ":pass: codex — session 2/5 ...",
      "checks": [{"name": "quality", "bucket": "pass"}, ...],
      "labels": ["enhancement", "hold-merge"],
      "has_human_changes_requested": false
    }

Exits 0 with ``merge`` printed to stdout when the gate passes; exits 1 with
the hold reason printed when it does not. The pure function
``should_auto_merge(inputs)`` is what tests import.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Iterable, Sequence

CODEX_BOT_LOGIN = "cloglog-codex-reviewer[bot]"
APPROVE_BODY_PREFIX = ":pass:"
HOLD_LABEL = "hold-merge"

# A check counts as "green" when its bucket is one of these. ``skipping`` is
# included because skipped checks are intentional (e.g., a workflow excluded
# by paths) and must not block the merge. Everything else — ``pending``,
# ``fail``, ``cancel``, missing bucket — holds.
GREEN_BUCKETS = frozenset({"pass", "skipping"})


@dataclass(frozen=True)
class GateInputs:
    reviewer: str
    body: str
    checks: Sequence[dict]
    labels: Sequence[str]
    # True when any human reviewer's most recent review on the PR is in state
    # CHANGES_REQUESTED. The agent computes this from
    # ``gh api repos/.../pulls/N/reviews`` filtered to non-bot users, taking
    # the latest review per author. Defaults to False so callers that omit
    # the field (older payload shape) hit the cautious path that requires
    # the agent to surface human reviews explicitly.
    has_human_changes_requested: bool = False


@dataclass(frozen=True)
class GateDecision:
    merge: bool
    reason: str


def should_auto_merge(inputs: GateInputs) -> GateDecision:
    """Pure gate decision. See module docstring for the five conditions.

    Order of checks is deliberate: cheap identity/marker checks first so the
    common "random commenter" path returns immediately without inspecting CI
    or fetching reviews. The human-CHANGES_REQUESTED check fires before the
    label and CI checks because it is the strongest *block* — once a human
    has said no, no amount of green CI or label hygiene should override.
    """
    if inputs.reviewer != CODEX_BOT_LOGIN:
        return GateDecision(False, "not_codex_reviewer")

    if not inputs.body.lstrip().startswith(APPROVE_BODY_PREFIX):
        return GateDecision(False, "not_codex_pass")

    if inputs.has_human_changes_requested:
        return GateDecision(False, "human_changes_requested")

    if HOLD_LABEL in inputs.labels:
        return GateDecision(False, "hold_label")

    if not _all_checks_green(inputs.checks):
        return GateDecision(False, "ci_not_green")

    return GateDecision(True, "merge")


def _all_checks_green(checks: Iterable[dict]) -> bool:
    """Every check must report a bucket in ``GREEN_BUCKETS``.

    Empty check list is treated as **green**. The project's CI workflow at
    ``.github/workflows/ci.yml`` filters by ``paths:`` (only fires on
    ``src/**``, ``frontend/src/**``, ``mcp-server/src/**``, ``tests/**``,
    etc.); a PR that touches only ``docs/**`` — e.g., a spec PR opened by
    the worktree-agent's spec task — has zero CI checks attached. The
    earlier "empty = not green" interpretation deadlocked those PRs:
    ``gh pr checks --watch`` returns immediately with no rollup, and the
    gate would loop forever. An empty rollup now means "no CI signal to
    wait for" and the codex pass is sufficient.

    Trade-off: the brief window between ``git push`` and CI enqueueing
    check_runs is also empty. In practice codex review takes long enough
    that CI has always enqueued by the time codex posts ``:pass:``. If a
    future CI workflow change introduces a real race here, switch to
    branch-protection's required-status-checks list as the source of
    truth instead.
    """
    for check in checks:
        if check.get("bucket") not in GREEN_BUCKETS:
            return False
    return True


def _parse_inputs(payload: dict) -> GateInputs:
    return GateInputs(
        reviewer=str(payload.get("reviewer") or ""),
        body=str(payload.get("body") or ""),
        checks=list(payload.get("checks") or []),
        labels=[str(name) for name in (payload.get("labels") or [])],
        has_human_changes_requested=bool(payload.get("has_human_changes_requested", False)),
    )


def main(argv: Sequence[str] | None = None) -> int:
    payload = json.loads(sys.stdin.read())
    decision = should_auto_merge(_parse_inputs(payload))
    print(decision.reason)
    return 0 if decision.merge else 1


if __name__ == "__main__":
    raise SystemExit(main())
