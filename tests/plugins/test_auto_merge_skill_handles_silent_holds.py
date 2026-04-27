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
    # T-314: the script is referenced via ${CLAUDE_PLUGIN_ROOT}/scripts/auto_merge_gate.py
    # since it is vendored into the plugin.
    assert body.count("${CLAUDE_PLUGIN_ROOT}/scripts/auto_merge_gate.py") >= 2, (
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
        "design doc no longer carries the §3.1 hold-reasons table; the five "
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


def test_design_doc_condition_three_does_not_promise_check_run_event() -> None:
    """Pin the §3.1 condition list against re-introducing the deadlock copy.

    PR #224 round 1 said condition 4 (CI checks) "waits for the next
    `check_run` webhook event"; codex round 2 caught that the same wording
    was still in the design doc's condition list even after the table below
    was corrected. The condition wording must point at the table, not at a
    nonexistent CI-success event.
    """
    body = DESIGN.read_text()
    # The whole point of the fix is that this exact phrasing must NOT recur.
    assert "waits for the next `check_run` webhook" not in body, (
        "design doc §3.1 reintroduces the wrong claim that the agent waits "
        "for a check_run webhook on success. Successful checks are never "
        "bridged to the worktree inbox — see the table for the real path."
    )


def test_worktree_agent_template_references_auto_merge_gate() -> None:
    """The agent-prompt template that worktree agents read at startup must
    point at the auto-merge gate.

    Codex round 3 caught that ``plugins/cloglog/agents/worktree-agent.md``
    described the pre-T-295 ``review_submitted`` flow without mentioning
    the new gate, leaving an instruction surface that would steer agents
    to the old in_progress path even when the codex bot had already passed.
    """
    template = (ROOT / "plugins" / "cloglog" / "agents" / "worktree-agent.md").read_text()
    # The template lists the inbox events for both the spec and impl task
    # paths. Both must steer agents at the new gate before falling through.
    assert template.count("Auto-Merge on Codex Pass") >= 2, (
        "worktree-agent.md no longer points at the github-bot skill's "
        "Auto-Merge on Codex Pass section from both the spec and impl "
        "task review_submitted notes — agents will follow the pre-T-295 "
        "in_progress path and miss the gate."
    )


def test_skill_uses_gh_pr_checks_for_bucket_field() -> None:
    """Self-test caught two ``gh`` API quirks on PR #224 round 5:

    1. ``gh pr view --jq`` does NOT accept ``--arg`` (only ``gh api`` does);
       the auto-merge bash crashed with ``unknown flag: --arg``.
    2. ``gh pr view --json statusCheckRollup`` returns CheckRun nodes with
       ``conclusion``/``status`` enums and NO ``bucket`` key — the gate
       always read ``bucket=null`` and held forever on ``ci_not_green``.

    The fix is to source checks from ``gh pr checks --json name,bucket``
    (the only `gh` surface that returns the normalized bucket) and
    assemble the payload with `jq -n --argjson` so we can inject the
    raw JSON arrays as typed values. Pin both against re-introduction.
    """
    body = SKILL.read_text()
    auto_merge_idx = body.index("### Auto-Merge on Codex Pass")
    next_section_idx = body.index("###", auto_merge_idx + 1)
    section = body[auto_merge_idx:next_section_idx]
    import re

    # Quirk 1: `gh pr view ... --arg` is invalid. Look for that pattern in
    # the bash code blocks and reject it.
    bad_args = re.findall(r"gh pr view[^\n`]*\\?\n[^\n`]*--arg", section)
    assert not bad_args, (
        "auto-merge section uses `gh pr view ... --arg`, which crashes with "
        "`unknown flag: --arg`. Use `gh api` with `--arg`, or fetch raw JSON "
        "and pipe through standalone `jq -c --argjson`."
    )

    # Quirk 2: the gate's `bucket` field must come from `gh pr checks`, not
    # from `gh pr view --json statusCheckRollup`. The skill's executable
    # bash blocks must reference `gh pr checks --json name,bucket` for the
    # actual data fetch. (We allow the cautionary prose mention of
    # statusCheckRollup as an anti-pattern warning.)
    assert "gh pr checks" in section and "name,bucket" in section, (
        "auto-merge bash no longer fetches checks via `gh pr checks --json "
        "name,bucket` — the gate cannot read the bucket field from the "
        "statusCheckRollup shape."
    )


def test_skill_invocation_block_sets_repo_before_using_it() -> None:
    """The auto-merge bash snippet must derive ``REPO`` itself.

    Codex round 4 caught that the first ``gh api repos/${REPO}/...`` call
    sat above any ``REPO=`` assignment, so a fresh shell would expand
    ``repos//pulls/<n>/reviews`` and the gate's
    ``has_human_changes_requested`` lookup would fail. Pin the assignment
    to land before the first use of ``$REPO`` in the auto-merge section.
    """
    body = SKILL.read_text()
    auto_merge_idx = body.index("### Auto-Merge on Codex Pass")
    next_section_idx = body.index("###", auto_merge_idx + 1)
    section = body[auto_merge_idx:next_section_idx]
    repo_assign_idx = section.find("REPO=$(gh repo view")
    repo_use_idx = section.find('"repos/${REPO}/')
    assert repo_assign_idx != -1, (
        "auto-merge section no longer derives REPO; the bash snippet will "
        "expand `repos//pulls/...` in a fresh shell."
    )
    assert repo_use_idx != -1, "auto-merge section no longer references repos/${REPO}/"
    assert repo_assign_idx < repo_use_idx, (
        "REPO= assignment must precede the first `repos/${REPO}/` lookup; "
        "otherwise the gate's has_human_changes_requested fetch fails."
    )


def test_skill_passes_human_changes_requested_to_gate() -> None:
    """The new fifth condition needs the agent to actually fetch human reviews.

    Otherwise a codex `:pass:` posted after a human `CHANGES_REQUESTED`
    review would slip past the gate (caught on PR #224 round 2).
    """
    body = SKILL.read_text()
    assert "has_human_changes_requested" in body, (
        "skill no longer wires `has_human_changes_requested` into the gate "
        "payload — codex `:pass:` could override a human change request."
    )
    # The lookup must hit the GitHub reviews API, not invent the value.
    assert "/reviews" in body and "CHANGES_REQUESTED" in body, (
        "skill no longer fetches /reviews to compute the human-change-request "
        "flag — the gate's fifth condition would always default to False."
    )
