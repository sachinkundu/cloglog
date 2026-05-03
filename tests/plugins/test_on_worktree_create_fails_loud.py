"""Pin tests: T-378.

cloglog's hand-written ``.cloglog/on-worktree-create.sh`` must fail loud
on any setup error — no silent partial setup.

The 2026-04-24 incident pattern: the script POSTed to
``/api/v1/agents/close-off-task`` before the worktree was registered, the
backend returned HTTP 404 ("Worktree not registered"), and the script
warn-and-continued. Every cleanly-completed worktree on the host then lacked
a close-off task and reconcile's close-wave delegation predicate (component
2) silently failed for them.

The fix is twofold:
  1. Launch SKILL Step 4b runs before 4c (pinned separately by
     ``test_launch_skill_register_before_on_worktree_create.py``).
  2. The script itself exits non-zero on any close-off-task failure (this
     file). With (1) in place a 404 means a real ordering regression, not a
     transient backend hiccup; combined with (2) the regression breaks CI
     instead of shipping.

The pins below assert *absence* of the warn-and-continue codepath and
*presence* of the explicit exit, so a future edit cannot quietly
re-introduce the silent path.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / ".cloglog/on-worktree-create.sh"


def _read() -> str:
    assert SCRIPT.exists(), f"{SCRIPT} missing — fix path or restore the script"
    return SCRIPT.read_text(encoding="utf-8")


def test_script_uses_set_e() -> None:
    """``set -e`` at the top is the floor for fail-loud — without it any
    intermediate command failure (uv sync, npm install, worktree-infra) is
    swallowed and the bootstrap continues with half-applied state."""
    body = _read()
    # Match `set -e`, `set -eu`, `set -euo pipefail`, etc.
    assert re.search(r"^set -e", body, flags=re.MULTILINE), (
        "on-worktree-create.sh must start with `set -e` (or stronger). "
        "Without it, intermediate failures during bootstrap (worktree-infra "
        "up, uv sync, npm install) are swallowed and the worktree ships "
        "half-applied."
    )


def test_close_off_task_block_has_no_warn_and_continue() -> None:
    """The close-off-task POST must not have a "WARN ... continuing" path.

    The original silent codepath logged a "WARN ... continuing" and
    proceeded. Any variant of "continuing" / "skipping" / "non-fatal" in
    the close-off-task block re-opens the 2026-04-24 silent-404 bug.
    """
    body = _read()
    forbidden = [
        "continuing",
        "Non-fatal",
        "non-fatal",
    ]
    for needle in forbidden:
        assert needle not in body, (
            f"on-worktree-create.sh must not warn-and-continue around the "
            f"close-off-task POST. Found {needle!r} in the script body — "
            "this is the 2026-04-24 silent-404 codepath. T-378 closed it; "
            "re-opening it ships every cleanly-completed worktree without a "
            "close-off task."
        )


def test_close_off_task_block_exits_on_error() -> None:
    """The close-off-task block must call ``exit 1`` (or ``exit`` non-zero)
    on a non-201 response. ``set -e`` alone is not enough because the curl
    invocation captures the HTTP code with ``|| echo "000"`` to surface the
    failure mode in the error message — that suppresses set -e."""
    body = _read()
    # Slice from the close-off-task POST to end of file to scope the assertion.
    idx = body.find("/api/v1/agents/close-off-task")
    assert idx != -1, (
        "on-worktree-create.sh must still POST to /api/v1/agents/close-off-task "
        "— the close-off task is what reconcile's close-wave delegation "
        "predicate (component 2) depends on."
    )
    tail = body[idx:]
    assert "exit 1" in tail, (
        "The close-off-task block must `exit 1` on a non-201 response. "
        "Without an explicit exit, the warn-and-continue path returns and "
        "the bootstrap proceeds with no close-off task on the board."
    )


def test_missing_api_key_aborts_bootstrap() -> None:
    """Missing CLOGLOG_API_KEY must abort the bootstrap, not warn-and-skip.

    Memory: silent skipping here is what hid 2026-04-24's
    every-host-misses-close-off-task pattern. If the operator has no API key,
    the worktree cannot file its close-off task — that is a setup error, not
    a transient condition, and ``on-worktree-create.sh`` should refuse to
    finish until the operator supplies one (see docs/setup-credentials.md).
    """
    body = _read()
    # The block guarding the no-key case must reach `exit` (not just an echo).
    # Match from the no-key guard to its closing `fi` at the start of a line
    # (multi-line `fi`, not the substring inside words like "file").
    no_key_block = re.search(
        r'if \[\[ -z "\$_api_key" \]\]; then\n(.*?)\n  fi\n',
        body,
        flags=re.DOTALL,
    )
    assert no_key_block, (
        "on-worktree-create.sh must guard the no-API-key case explicitly so "
        "the failure mode is visible at the surface."
    )
    assert "exit" in no_key_block.group(1), (
        "The no-CLOGLOG_API_KEY guard must `exit` (non-zero), not just echo "
        "and continue. Continuing without an API key means the close-off-task "
        "POST is silently skipped — the exact 2026-04-24 failure mode T-378 "
        "closes."
    )
