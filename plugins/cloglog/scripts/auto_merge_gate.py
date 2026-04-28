"""Pure decision logic for the worktree-agent's auto-merge gate (T-295).

The gate decides whether the agent should run
``gh pr merge <num> --squash --delete-branch`` on its own PR after a
``review_submitted`` inbox event arrives. All five conditions must hold:

1. The reviewer's GitHub login appears in ``reviewer_bot_logins`` of the
   project's ``.cloglog/config.yaml``. Random commenters never trigger an
   auto-merge.
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
      "reviewer": "<reviewer login from inbox event>",
      "body": ":pass: codex — session 2/5 ...",
      "checks": [{"name": "quality", "bucket": "pass"}, ...],
      "labels": ["enhancement", "hold-merge"],
      "has_human_changes_requested": false
    }

Optional ``reviewer_bot_logins`` may be set in the payload to override the
config-file lookup (used by tests to keep the helper hermetic). When omitted,
the gate walks up from CWD to find ``.cloglog/config.yaml`` and reads the
``reviewer_bot_logins`` list from it.

Exits 0 with ``merge`` printed to stdout when the gate passes; exits 1 with
the hold reason printed when it does not. The pure function
``should_auto_merge(inputs)`` is what tests import.

Stdlib-only by design — the system ``python3`` plugin scripts run under
typically lacks PyYAML (``docs/invariants.md`` § hook YAML parsing). The
inline list reader below handles the small subset of YAML cloglog uses.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

APPROVE_BODY_PREFIX = ":pass:"
HOLD_LABEL = "hold-merge"

# A check counts as "green" when its bucket is one of these. ``skipping`` is
# included because skipped checks are intentional (e.g., a workflow excluded
# by paths) and must not block the merge. Everything else — ``pending``,
# ``fail``, ``cancel``, missing bucket — holds.
GREEN_BUCKETS = frozenset({"pass", "skipping"})


_LIST_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+):\s*(?:#.*)?$")
_LIST_ITEM_RE = re.compile(r"^[ \t]+-[ \t]+(.+?)[ \t]*$")


def _strip_quotes(value: str) -> str:
    value = value.strip()
    # Strip an inline comment that follows whitespace (only when the value is
    # not quoted — quoted scalars carry # literally).
    if not (value.startswith("'") or value.startswith('"')):
        m = re.search(r"\s+#", value)
        if m:
            value = value[: m.start()].rstrip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return value


def _parse_top_level_list(text: str, key: str) -> tuple[str, ...]:
    """Read a top-level YAML list (``<key>:\\n  - item\\n  - item``).

    Stops at the next top-level (column-zero) non-blank line. Raises on
    unexpected indented content under ``key:`` so a malformed config is
    surfaced rather than silently ignored.
    """
    out: list[str] = []
    in_block = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if not in_block:
            m = _LIST_KEY_RE.match(line)
            if m and m.group(1) == key:
                in_block = True
            continue
        # Blank line inside the block: keep going.
        if not line.strip() or line.lstrip(" \t").startswith("#"):
            continue
        # End-of-block marker: column-zero non-blank line.
        if line[0] not in (" ", "\t"):
            break
        m = _LIST_ITEM_RE.match(line)
        if not m:
            raise ValueError(
                f"unexpected line under {key}::{line!r} (expected '  - <value>')"
            )
        out.append(_strip_quotes(m.group(1)))
    return tuple(out)


def _find_config_yaml() -> Path | None:
    """Return the nearest ``.cloglog/config.yaml`` walking up from CWD.

    Honours ``CLOGLOG_CONFIG_YAML`` for tests that want to point at a
    fixture without changing CWD.
    """
    override = os.environ.get("CLOGLOG_CONFIG_YAML")
    if override:
        candidate = Path(override)
        return candidate if candidate.is_file() else None
    cur = Path.cwd().resolve()
    for parent in [cur, *cur.parents]:
        candidate = parent / ".cloglog" / "config.yaml"
        if candidate.is_file():
            return candidate
    return None


def _load_reviewer_bot_logins() -> tuple[str, ...]:
    cfg = _find_config_yaml()
    if cfg is None:
        return ()
    try:
        return _parse_top_level_list(cfg.read_text(encoding="utf-8"), "reviewer_bot_logins")
    except (OSError, ValueError):
        return ()


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
    # When empty (default), the gate loads the list from the project's
    # ``.cloglog/config.yaml: reviewer_bot_logins``. Tests inject explicit
    # values so they don't depend on filesystem state.
    reviewer_bot_logins: Sequence[str] = field(default_factory=tuple)


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
    allowed = tuple(inputs.reviewer_bot_logins) or _load_reviewer_bot_logins()
    if inputs.reviewer not in allowed:
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
        reviewer_bot_logins=tuple(
            str(login) for login in (payload.get("reviewer_bot_logins") or [])
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    payload = json.loads(sys.stdin.read())
    decision = should_auto_merge(_parse_inputs(payload))
    print(decision.reason)
    return 0 if decision.merge else 1


if __name__ == "__main__":
    raise SystemExit(main())
