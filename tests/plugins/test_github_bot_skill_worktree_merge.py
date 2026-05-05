"""Pin test: github-bot SKILL guards --delete-branch when running in a worktree.

T-438 fix #1.

``gh pr merge --squash --delete-branch`` triggers a local branch deletion that
requires switching to another branch first (usually main). When the agent runs
inside a git worktree, main is already checked out in the primary worktree —
the branch switch fails with a collision error, and the PR merge hangs or
aborts. The fix: detect worktree context via ``git rev-parse --git-dir`` and
skip ``--delete-branch``; the remote branch is deleted by GitHub on merge.

Silent-failure shape: a SKILL edit that removes the guard (e.g., inlining the
merge command during a refactor) would let the agent successfully merge the PR
but then fail on local branch cleanup — either hanging or leaving the agent in
an error state with no PR-merge notification sent.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL = REPO_ROOT / "plugins/cloglog/skills/github-bot/SKILL.md"


def _read(p: Path) -> str:
    assert p.exists(), f"{p} missing"
    return p.read_text(encoding="utf-8")


def test_github_bot_skill_detects_worktree_for_delete_branch() -> None:
    """The SKILL must detect worktree context before running --delete-branch."""
    text = _read(SKILL)
    assert "worktrees" in text, (
        "github-bot SKILL.md must detect worktree context by checking "
        "git rev-parse --git-dir for 'worktrees' before passing "
        "--delete-branch to gh pr merge. T-438 fix #1."
    )


def test_github_bot_skill_uses_conditional_merge_flags() -> None:
    """The SKILL must use a conditional variable for --delete-branch."""
    text = _read(SKILL)
    assert "WORKTREE_MERGE_FLAGS" in text, (
        "github-bot SKILL.md must use WORKTREE_MERGE_FLAGS (or equivalent "
        "conditional) to omit --delete-branch when running inside a git "
        "worktree. Without this, gh pr merge fails on local branch cleanup "
        "because main is already checked out in the primary worktree. "
        "T-438 fix #1."
    )
