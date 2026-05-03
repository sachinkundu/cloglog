"""Pin tests: T-378.

The launch skill's Step 4 must call ``register_agent`` (Step 4b) **before**
running the project-specific ``on-worktree-create.sh`` (Step 4c).

Why: ``.cloglog/on-worktree-create.sh`` posts to ``/api/v1/agents/close-off-task``
which requires the worktree to be registered. The 2026-04-24 incident (memory:
``project_worktree_create_register_bug``) was that the script ran before
register, the backend returned 404 "Worktree not registered", and the script
warn-and-continued — every cleanly-completed worktree on the host then lacked
a close-off task and reconcile's close-wave delegation predicate (component 2)
silently failed.

The SKILL prose was already in the right order (4a worktree-add → 4b register
→ 4c on-worktree-create.sh) but no automated guard pinned it. T-378 closes
the gap so a future re-ordering breaks CI rather than shipping.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LAUNCH_SKILL = REPO_ROOT / "plugins/cloglog/skills/launch/SKILL.md"


def _read() -> str:
    assert LAUNCH_SKILL.exists(), f"{LAUNCH_SKILL} missing"
    return LAUNCH_SKILL.read_text(encoding="utf-8")


def _step_offset(body: str, heading_re: str) -> int:
    """Return the byte offset of the first line matching the heading regex."""
    m = re.search(heading_re, body, flags=re.MULTILINE)
    assert m, f"Could not locate step heading {heading_re!r} in launch SKILL.md"
    return m.start()


def test_register_agent_step_appears_before_on_worktree_create_step() -> None:
    """Step 4b (register_agent) must appear before Step 4c (on-worktree-create.sh)
    in the launch SKILL prose. Re-ordering reopens the 2026-04-24 silent-404
    bug."""
    body = _read()
    register_offset = _step_offset(body, r"^### 4b\..*[Rr]egister")
    create_offset = _step_offset(body, r"^### 4c\.")
    # Sanity: 4c is in fact the on-worktree-create step (not some unrelated
    # 4c heading inserted later). Scan the next 30 lines for the script name.
    section_4c = body[create_offset : create_offset + 2000]
    assert "on-worktree-create.sh" in section_4c, (
        "Step 4c must be the project-specific bootstrap step (the one that "
        "invokes on-worktree-create.sh). If this fails the heading layout "
        "drifted — re-anchor the test to the new step number."
    )
    assert register_offset < create_offset, (
        "Step 4b (register_agent) must appear before Step 4c "
        "(on-worktree-create.sh). Reversing the order means the project-"
        "specific bootstrap runs before the worktree is registered, and "
        "the close-off-task POST returns 404. See memory "
        "project_worktree_create_register_bug.md (2026-04-24)."
    )


def test_step_4b_invokes_register_agent_with_worktree_args() -> None:
    """Step 4b must name ``register_agent`` and reference the worktree
    name/path arguments — the prose-level contract that the supervisor
    passes both before invoking the bootstrap script."""
    body = _read()
    # Slice from "### 4b." to the next "### " heading.
    section = re.search(r"### 4b\.(.*?)(?=^### )", body, flags=re.DOTALL | re.MULTILINE)
    assert section, "Step 4b section missing"
    text = section.group(1)
    assert "register_agent" in text, (
        "Step 4b must invoke `mcp__cloglog__register_agent` by name so a "
        "future reader cannot ambiguate the registration call."
    )
    assert "worktree" in text.lower(), (
        "Step 4b prose must mention worktree name/path so the "
        "register-before-create contract is visible at the surface."
    )


def test_step_4b_explains_why_register_runs_before_bootstrap() -> None:
    """Step 4b must explain that registration happens before the bootstrap
    script — otherwise a future edit can re-order the steps without realising
    the bootstrap depends on it.

    The current prose says "done here (not deferred to the agent) so the
    board reflects the launch immediately". That alone is not strong enough
    against re-ordering relative to 4c — we also need the close-off-task
    dependency made explicit so a human reviewer can catch the regression
    before CI runs.
    """
    body = _read()
    section = re.search(r"### 4b\.(.*?)(?=^### )", body, flags=re.DOTALL | re.MULTILINE)
    assert section, "Step 4b section missing"
    text = section.group(1)
    # Either the close-off-task dependency or the explicit "before
    # on-worktree-create.sh" ordering must be called out in 4b's body.
    assert "on-worktree-create" in text or "close-off-task" in text, (
        "Step 4b must explicitly state that registration happens BEFORE "
        "on-worktree-create.sh (which posts to /api/v1/agents/close-off-task "
        "and needs the worktree to be registered). Without that explanation, "
        "a future edit can swap 4b and 4c and only learn about the dependency "
        "from a 404 in production."
    )
