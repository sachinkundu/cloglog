"""Backstop: T-270.

Reconcile's Step 5 used to tear down worktrees directly, destroying
``<worktree>/shutdown-artifacts/{work-log,learnings}.md`` before
``close-wave`` could archive them to ``docs/work-logs/`` or fold
learnings into CLAUDE.md. T-270 resolves the split-brain by introducing
a Step 5.0 that delegates the teardown of **cleanly-completed**
worktrees to close-wave; Cases A/B/C remain the fallback for agents
that crashed, wedged, or never produced shutdown-artifacts.

These assertions pin the structure — one ``assert`` per load-bearing
component — so a future partial deletion (e.g. someone drops the
``pr_merged`` predicate check while refactoring) fails loudly with a
pointer at the missing piece, rather than silently reintroducing the
2026-04-23 regression.

The canonical specification of the unified teardown flow lives in
``docs/design/agent-lifecycle.md`` §5.5 (T-270). close-wave's
reconcile-callable entry point is documented at the top of
``plugins/cloglog/skills/close-wave/SKILL.md``.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

RECONCILE_SKILL = REPO_ROOT / "plugins/cloglog/skills/reconcile/SKILL.md"
CLOSE_WAVE_SKILL = REPO_ROOT / "plugins/cloglog/skills/close-wave/SKILL.md"
AGENT_LIFECYCLE = REPO_ROOT / "docs/design/agent-lifecycle.md"


def _read(p: Path) -> str:
    assert p.exists(), f"{p} missing — fix the path or the file was moved"
    return p.read_text(encoding="utf-8")


def test_reconcile_skill_has_close_wave_delegation_branch() -> None:
    """Step 5.0 must call out the delegation explicitly. Without a
    grep-able phrase a future edit can quietly remove the branch and
    reconcile silently reverts to the destructive teardown path."""
    body = _read(RECONCILE_SKILL)
    assert "Step 5.0" in body, (
        "reconcile SKILL.md must introduce a Step 5.0 section gating the "
        "Cases A/B/C teardown — it is the delegation branch T-270 added."
    )
    assert "delegate the entire teardown to close-wave" in body, (
        "reconcile Step 5.0 must state the delegation verbatim so the "
        "intent survives ruff/prettier reformats and future partial edits."
    )


def test_reconcile_skill_references_all_three_predicate_components() -> None:
    """Three separate asserts — one per predicate component — so a
    future partial deletion (someone drops the `pr_merged` check during
    a rewrite) fails loudly against the specific missing piece."""
    body = _read(RECONCILE_SKILL)

    assert "shutdown-artifacts/work-log.md" in body, (
        "predicate component 1 (filesystem check for the work-log "
        "artifact) must be referenced in reconcile Step 5.0. Without it "
        "reconcile would delegate to close-wave on worktrees that have "
        "nothing to archive."
    )
    assert "close-off task" in body.lower() or "close-off task queued" in body.lower(), (
        "predicate component 2 (a `Close worktree <wt-name>` task exists "
        "in backlog) must be referenced in reconcile Step 5.0. Without "
        "it reconcile would delegate before the close-off task has been "
        "filed, leaving close-wave with no task to close."
    )
    assert 'title == f"Close worktree {wt_name}"' in body, (
        "predicate component 2 must pin the title-equality match pattern. "
        "Codex PR #194 round 1 caught an earlier version that filtered "
        "`get_board` by `worktree_id == <target_wt_id>`; close-off tasks "
        "carry the main agent's worktree_id, not the target's, so that "
        "filter would never match and cleanly-completed worktrees would "
        "fall through to Cases A/C and get torn down directly."
    )
    assert "pr_merged" in body, (
        "predicate component 3 (task resolution state across `pr_merged`, "
        "`status`, and `pr_url`) must be referenced in reconcile Step 5.0. "
        "Without it reconcile would delegate for worktrees whose PRs have "
        "not actually merged."
    )
    for accepted_terminal_state in (
        '`status == "done"`',
        '`status == "review"` AND `pr_merged == True`',
        '`status == "review"` AND `pr_url is None`',
    ):
        assert accepted_terminal_state in body, (
            "predicate component 3 must accept all three project-completion "
            "terminal states per docs/design/agent-lifecycle.md §1 and "
            f"src/board/templates.py:24-25 — missing: {accepted_terminal_state}. "
            "A stricter `pr_merged=True`-everywhere check (codex PR #194 "
            "round 2 MEDIUM) falsely rejects cleanly-completed worktrees "
            "whose last task was no-PR (skip_pr=True) or whose user already "
            "moved one card to `done`, re-creating the T-270 artifact-loss "
            "bug the delegation was written to prevent."
        )


def test_reconcile_skill_keeps_cases_a_b_c_as_fallbacks() -> None:
    """T-270 only adds a new early branch; it must not remove the
    dirty-path handlers. Agents that crash, wedge, or never write
    shutdown-artifacts still need cooperative-shutdown / force_unregister."""
    body = _read(RECONCILE_SKILL)
    for case_header in (
        "### Case A — PR merged, agent still registered",
        "### Case B — Wedged agent",
        "### Case C — Orphaned worktree",
    ):
        assert case_header in body, (
            f"reconcile SKILL.md lost '{case_header}'. Cases A/B/C are the "
            "dirty-path fallback for worktrees that fail the predicate; "
            "removing them collapses the split-brain fix back into a single "
            "broken path."
        )


def test_close_wave_skill_documents_reconcile_delegation() -> None:
    """Close-wave must declare its reconcile-callable entry point at the
    top. A reconcile caller that cannot find documented invocation
    semantics will either (a) invoke the user-driven flow and stall on
    the user-confirmation prompt, or (b) skip close-wave entirely and
    re-introduce the destructive reconcile teardown."""
    body = _read(CLOSE_WAVE_SKILL)
    assert "Invocation modes" in body, (
        "close-wave SKILL.md must declare an 'Invocation modes' section "
        "near the top documenting user-driven vs reconcile-delegated "
        "entry points."
    )
    assert "Reconcile delegation" in body or "reconcile delegation" in body.lower(), (
        "close-wave Invocation modes must name the 'Reconcile delegation' "
        "mode explicitly so a reader can grep for it."
    )
    assert "Skip Step 1.5" in body or "skip Step 1.5" in body.lower(), (
        "close-wave reconcile-mode must state that user confirmation "
        "(Step 1.5) is skipped. Otherwise reconcile's auto-fix flow "
        "stalls waiting for a prompt that will never be answered."
    )
    assert "reconcile-<wt-name>" in body, (
        "close-wave reconcile-mode must override the `<wave-name>` "
        "variable to `reconcile-<wt-name>` — NOT a full filename. Codex "
        "PR #194 round 2 HIGH caught an earlier version that set the "
        "override to `reconcile-<date>-<wt-name>.md`, which would nest "
        "into Step 4's `docs/work-logs/<date>-<wave-name>.md` template "
        "and produce `<date>-reconcile-<date>-<wt-name>.md.md`."
    )


def test_agent_lifecycle_documents_unified_teardown_flow() -> None:
    """§5.5 is the authoritative spec for the reconcile-as-arbiter rule.
    If this disappears, future agents will re-invent the split-brain."""
    body = _read(AGENT_LIFECYCLE)
    assert "Reconcile is the arbiter" in body, (
        "docs/design/agent-lifecycle.md §5 must state the unified-flow "
        "rule verbatim ('Reconcile is the arbiter. Close-wave is the "
        "clean path. force_unregister is the dirty path.') so future "
        "readers cannot ambiguate ownership."
    )
    assert "T-270" in body, (
        "docs/design/agent-lifecycle.md §5.5 must reference T-270 as the "
        "task that introduced the unified teardown flow. Tracking the "
        "origin lets future maintainers locate the incident analysis."
    )
    assert "every assigned task has `pr_merged=True`." not in body, (
        "docs/design/agent-lifecycle.md §5.5 must NOT restate predicate "
        "component 3 as the stricter 'every assigned task has "
        "`pr_merged=True`' — that was the codex PR #194 round 3 MEDIUM "
        "regression. The §5.5 restatement has to list all three accepted "
        "terminal states (done; review+pr_merged; review+pr_url=None) "
        "OR defer to reconcile Step 5.0 instead of collapsing to the "
        "overly-strict form."
    )


def test_no_doc_retains_the_stricter_pr_merged_only_predicate() -> None:
    """The 'pr_merged=True everywhere' wording was wrong in three places
    that all pointed at the same spec: reconcile's Delegation summary,
    close-wave's Invocation modes summary, and agent-lifecycle §5.5.
    Codex PR #194 round 3 MEDIUM found that fixing one and leaving the
    other two still regressed the predicate. Pin all three."""
    for path in (RECONCILE_SKILL, CLOSE_WAVE_SKILL, AGENT_LIFECYCLE):
        body = _read(path)
        assert "every assigned task has `pr_merged=True`." not in body, (
            f"{path.relative_to(REPO_ROOT)} retains the stricter "
            "'every assigned task has `pr_merged=True`.' wording. A "
            "cleanly-completed worktree whose last task shipped no-PR "
            "(skip_pr=True per agent-lifecycle §1 Trigger B) would be "
            "misclassified as dirty-path and have its shutdown-artifacts "
            "deleted before close-wave could archive them — the exact "
            "T-270 regression the delegation was written to prevent."
        )
        assert "every assigned task `pr_merged=True`" not in body, (
            f"{path.relative_to(REPO_ROOT)} retains the stricter summary "
            "phrasing. Same reasoning as above — the summary must not "
            "collapse the three accepted terminal states back to the "
            "strict pr_merged=True form."
        )


def test_no_doc_retains_full_filename_wave_name_override() -> None:
    """The close-wave reconcile-mode override is a `<wave-name>`
    substitution (`reconcile-<wt-name>`), NOT a full filename. Codex PR
    #194 round 3 HIGH found that reconcile's Delegation summary still
    said 'overrides the work-log naming to reconcile-<date>-<wt-name>.md'
    even after close-wave was fixed — the two docs disagreed. Pin the
    full-filename shape out of both."""
    for path in (RECONCILE_SKILL, CLOSE_WAVE_SKILL):
        body = _read(path)
        assert "reconcile-<date>-<wt-name>.md" not in body, (
            f"{path.relative_to(REPO_ROOT)} retains the full-filename "
            "shape `reconcile-<date>-<wt-name>.md`. Close-wave Step 4's "
            "template is `docs/work-logs/<date>-<wave-name>.md`; the "
            "reconcile override must set `<wave-name>` = "
            "`reconcile-<wt-name>`, not a full filename that nests into "
            "the template and produces `<date>-reconcile-<date>-<wt-name>.md.md`."
        )
