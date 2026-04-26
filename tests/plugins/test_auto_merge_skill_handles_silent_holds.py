"""Pin the auto-merge skill's handling of the two webhook-silent hold reasons (T-295).

The webhook consumer at ``src/gateway/webhook_consumers.py`` only writes
``ci_failed`` (no event for ``success``/``pending``) and ``src/gateway/webhook.py``
only bridges ``opened/synchronize/closed`` ``pull_request`` actions (label
changes never reach the worktree inbox). That means two of the gate's hold
reasons have NO inbox event that re-runs them automatically:

- ``ci_not_green`` — handler must wait synchronously inside the same
  ``review_submitted`` invocation (``gh pr checks --watch``), then re-evaluate
  exactly once.
- ``hold_label`` — clearing the override requires human action: manual merge
  or a push that re-triggers codex.

A first-pass version of this skill claimed both would be re-triggered "by the
next webhook event" — codex flagged the gap on PR #224 (one MEDIUM + one HIGH).
This test pins that the corrected language stays put.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SKILL = ROOT / "plugins" / "cloglog" / "skills" / "github-bot" / "SKILL.md"
DESIGN = ROOT / "docs" / "design" / "agent-lifecycle.md"


def test_skill_blocks_synchronously_on_ci_pending() -> None:
    """The handler must `gh pr checks --watch` for ``ci_not_green``."""
    body = SKILL.read_text()
    assert "ci_not_green)" in body, "ci_not_green case missing from skill bash"
    # The watch invocation is the only thing that breaks the deadlock.
    assert 'gh pr checks "$PR_NUM" --watch' in body, (
        "ci_not_green path no longer waits synchronously on `gh pr checks --watch` — "
        "without it the gate deadlocks when codex passes before CI terminates "
        "(no inbox event fires for successful CI)."
    )
    # And re-evaluates exactly once after the wait.
    assert body.count("plugins/cloglog/scripts/auto_merge_gate.py") >= 2, (
        "ci_not_green path no longer re-runs the gate after `--watch` returns — "
        "the wait is pointless without a re-evaluation."
    )


def test_skill_documents_hold_label_human_action() -> None:
    """Removing ``hold-merge`` does NOT re-run the gate — must be documented."""
    body = SKILL.read_text()
    assert "hold_label)" in body
    # Must call out that label removal alone does NOT re-trigger.
    needle = "label-removal does NOT"
    assert needle in body, (
        f"skill no longer warns that {needle!r} — agents will assume the next "
        "label-change webhook re-runs the gate, but the consumer ignores those."
    )
    # Must point at the actual remediation paths.
    assert "manual" in body.lower() and "push" in body.lower(), (
        "skill no longer names the human remediation paths (manual merge / "
        "push to retrigger codex)."
    )


def test_design_doc_describes_real_retrigger_surface() -> None:
    """``docs/design/agent-lifecycle.md`` §3.1 must match the skill."""
    body = DESIGN.read_text()
    assert "Hold reasons and re-trigger paths" in body, (
        "design doc no longer carries the §3.1 hold-reasons table; the four "
        "reasons must each name their re-trigger path explicitly."
    )
    # The doc must also call out the `--watch` strategy and the no-event
    # reality for label changes.
    assert "--watch" in body, "design doc no longer describes the `--watch` re-evaluation"
    assert "label changes never reach the agent" in body, (
        "design doc no longer states that label changes are not bridged to "
        "the worktree inbox — that fact is the whole reason `hold_label` "
        "needs human action."
    )
