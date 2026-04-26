"""Backstop: T-301 / T-prod-7.

Reconcile historically used the same detached-HEAD-push workaround as
close-wave for any fold-style fix the operator made while running
reconciliation. The dev clone now has a writable local `main`, so any
file fix surfaced during reconcile ships via the standard
`wt-reconcile-<date>-<topic>` branch + PR flow
(`docs/design/prod-branch-tracking.md` §7).

Absence asserts pin out the retired patterns. The reconcile skill
itself does not author committed file changes today, but the auto-fix
rule has to make the standard flow explicit so a future operator
edit-by-reflex does not regress to direct-`main` commits.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL = REPO_ROOT / "plugins/cloglog/skills/reconcile/SKILL.md"


def _read() -> str:
    assert SKILL.exists(), f"{SKILL} missing — fix the path or the file was moved"
    return SKILL.read_text(encoding="utf-8")


def test_reconcile_skill_does_not_use_detached_head_workaround() -> None:
    body = _read()
    assert "git checkout --detach origin/main" not in body, (
        "reconcile SKILL.md must not direct the main agent to use "
        "`git checkout --detach origin/main`. That was the workaround "
        "for the dev worktree's pre-T-300 inability to sit on local "
        "`main`; T-prod-7 retired it in favour of `wt-reconcile-*` "
        "branch + PR (see `docs/design/prod-branch-tracking.md` §7)."
    )


def test_reconcile_skill_does_not_push_via_refspec_to_wt_close_branch() -> None:
    body = _read()
    assert "HEAD:refs/heads/wt-close-" not in body, (
        "reconcile SKILL.md must not push via "
        "`git push origin HEAD:refs/heads/wt-close-...`. Reconcile-"
        "originated fixes ship on `wt-reconcile-<date>-<topic>` "
        "branches via `gh pr create`, not by detached-HEAD refspec push "
        "to a wt-close branch."
    )


def test_reconcile_skill_does_not_use_chore_close_branch_prefix() -> None:
    body = _read()
    assert "chore-close-" not in body, (
        "reconcile SKILL.md must not reference the legacy `chore-close-` "
        "branch prefix. Reconcile fixes ship under `wt-reconcile-*`, "
        "not `chore-close-*`."
    )


def test_reconcile_skill_documents_wt_reconcile_branch_pr_flow() -> None:
    """Positive companion: the new flow must be present and grep-able."""
    body = _read()
    assert "git checkout -b wt-reconcile-" in body, (
        "reconcile SKILL.md must show the `git checkout -b "
        "wt-reconcile-<date>-<topic>` step. Without it the auto-fix "
        "guidance leaves the operator with no documented branching "
        "recipe and they reach for direct-`main` commits by reflex."
    )
    assert "gh pr create --base main --head wt-reconcile-" in body, (
        "reconcile SKILL.md must spell out the `gh pr create --base "
        "main --head wt-reconcile-...` invocation. Otherwise the docs "
        "describe a flow whose end-to-end command sequence is "
        'improvised — the same ergonomics issue CLAUDE.md "Auto-merge '
        '/ PR gates" calls out (run any documented executable command '
        "sequence end-to-end before merging the docs that describe it)."
    )
    assert 'GH_TOKEN="$BOT_TOKEN" gh pr create' in body, (
        "reconcile SKILL.md must show the bot-authenticated PR-creation "
        'form (`GH_TOKEN="$BOT_TOKEN" gh pr create ...`). Codex PR '
        "#230 round 1 MEDIUM caught a draft that showed a bare "
        "`gh pr create`; an operator following that for a "
        "wt-reconcile-* fix would open the PR under their personal "
        "`gh auth` and break the bot-identity invariant the github-bot "
        "skill exists to enforce."
    )
