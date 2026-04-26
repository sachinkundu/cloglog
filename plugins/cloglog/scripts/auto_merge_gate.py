"""Pure decision logic for the worktree-agent's auto-merge gate (T-295).

The gate decides whether the agent should run
``gh pr merge <num> --squash --delete-branch`` on its own PR after a
``review_submitted`` inbox event arrives. All four conditions must hold:

1. The reviewer is the codex bot (``cloglog-codex-reviewer[bot]``) — random
   commenters never trigger an auto-merge.
2. The review body, after ``lstrip()``, starts with the codex approval marker
   ``:pass:`` (matches ``_APPROVE_BODY_PREFIX`` in
   ``src/gateway/review_engine.py``).
3. Every CI check on the PR has terminated with ``success`` (or is an
   intentional ``skipping``). Pending or failing checks block the merge — the
   agent waits for the next webhook event.
4. The PR does not carry the ``hold-merge`` label.

The CLI form reads a single JSON object on stdin with the fields:

    {
      "reviewer": "cloglog-codex-reviewer[bot]",
      "body": ":pass: codex — session 2/5 ...",
      "checks": [{"name": "quality", "bucket": "pass"}, ...],
      "labels": ["enhancement", "hold-merge"]
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


@dataclass(frozen=True)
class GateDecision:
    merge: bool
    reason: str


def should_auto_merge(inputs: GateInputs) -> GateDecision:
    """Pure gate decision. See module docstring for the four conditions.

    Order of checks is deliberate: cheap identity/marker checks first so the
    common "random commenter" path returns immediately without inspecting CI.
    """
    if inputs.reviewer != CODEX_BOT_LOGIN:
        return GateDecision(False, "not_codex_reviewer")

    if not inputs.body.lstrip().startswith(APPROVE_BODY_PREFIX):
        return GateDecision(False, "not_codex_pass")

    if HOLD_LABEL in inputs.labels:
        return GateDecision(False, "hold_label")

    if not _all_checks_green(inputs.checks):
        return GateDecision(False, "ci_not_green")

    return GateDecision(True, "merge")


def _all_checks_green(checks: Iterable[dict]) -> bool:
    """Every check must report a bucket in ``GREEN_BUCKETS``.

    Empty check list is treated as NOT green — a PR with zero CI checks
    configured should not be auto-merged on a codex pass alone. The project
    runs a ``quality`` workflow on every PR; an empty list means the rollup
    has not landed yet (pending).
    """
    seen_any = False
    for check in checks:
        seen_any = True
        if check.get("bucket") not in GREEN_BUCKETS:
            return False
    return seen_any


def _parse_inputs(payload: dict) -> GateInputs:
    return GateInputs(
        reviewer=str(payload.get("reviewer") or ""),
        body=str(payload.get("body") or ""),
        checks=list(payload.get("checks") or []),
        labels=[str(name) for name in (payload.get("labels") or [])],
    )


def main(argv: Sequence[str] | None = None) -> int:
    payload = json.loads(sys.stdin.read())
    decision = should_auto_merge(_parse_inputs(payload))
    print(decision.reason)
    return 0 if decision.merge else 1


if __name__ == "__main__":
    raise SystemExit(main())
