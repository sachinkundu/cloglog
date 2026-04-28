"""Backstop: T-301 / T-prod-7.

The close-wave skill historically committed fold/reconcile updates
in-place on the main clone (detached HEAD) and pushed via the bot to a
`wt-close-*` branch — a workaround for the dev worktree's inability to
sit on local `main`. Post-T-300 the dev clone has a writable local
`main`, and close-wave moved to the standard `wt-close-<date>-<wave>`
branch + PR flow (see `docs/design/prod-branch-tracking.md` §7).

These pin tests assert *absence* of the retired patterns. Per the
codebase's leak-after-fix rule, an absence assert is the only way to
catch a future revert that re-introduces the detached-HEAD push (the
bug looked correct in tests because the workaround "worked" — the cost
was integration-flow rot, not a unit-test failure).
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL = REPO_ROOT / "plugins/cloglog/skills/close-wave/SKILL.md"


def _read() -> str:
    assert SKILL.exists(), f"{SKILL} missing — fix the path or the file was moved"
    return SKILL.read_text(encoding="utf-8")


def test_close_wave_skill_does_not_use_detached_head_workaround() -> None:
    body = _read()
    assert "git checkout --detach origin/main" not in body, (
        "close-wave SKILL.md must not direct the main agent to use "
        "`git checkout --detach origin/main`. That was the workaround "
        "for the dev worktree's pre-T-300 inability to sit on local "
        "`main`; T-prod-7 retired it in favour of `wt-close-*` branch "
        "+ PR (`docs/design/prod-branch-tracking.md` §7). A revert "
        "would silently restore the detached-HEAD-push flow that the "
        "T-prod-8 pre-commit guard exists to prevent."
    )


def test_close_wave_skill_does_not_push_via_refspec_to_wt_close_branch() -> None:
    body = _read()
    assert "HEAD:refs/heads/wt-close-" not in body, (
        "close-wave SKILL.md must not push via "
        "`git push origin HEAD:refs/heads/wt-close-...` from a detached "
        "HEAD. That refspec push pattern only exists to ship a commit "
        "made in detached-HEAD state to a remote branch without ever "
        "checking out the branch locally — exactly the workaround "
        "T-prod-7 retired. The standard flow is `git checkout -b "
        "wt-close-<date>-<wave>` + `gh pr create`."
    )


def test_close_wave_skill_does_not_use_chore_close_branch_prefix() -> None:
    body = _read()
    assert "chore-close-" not in body, (
        "close-wave SKILL.md must not reference the legacy `chore-close-` "
        "branch prefix. The current convention is `wt-close-<date>-"
        "<wave-name>` (Step 10), keeping every branch under the `wt-*` "
        "namespace that worktree-aware tooling already understands."
    )


def test_close_wave_skill_documents_branch_pr_flow() -> None:
    """Positive companion to the absence asserts above: the new flow
    must be present and grep-able. Without this, a future edit could
    delete the new pattern without re-introducing the old one and the
    skill would silently lose its commit guidance."""
    body = _read()
    assert "git checkout -b wt-close-" in body, (
        "close-wave SKILL.md must show the `git checkout -b "
        "wt-close-<date>-<wave-name>` step (Step 10). That is the "
        "branch the entire fold lands on; without it, a reader has no "
        "way to know which branch the work-log/learnings PR comes from."
    )
    assert "gh pr create --base main --head wt-close-" in body, (
        "close-wave SKILL.md must show the `gh pr create --base main "
        "--head wt-close-...` invocation (Step 13). Codex auto-merge "
        "and CI checks fire off the PR; the skill must spell out the "
        "PR-creation command so the operator does not improvise."
    )
    assert "git merge --ff-only origin/main" in body, (
        "close-wave SKILL.md must keep the `git merge --ff-only "
        "origin/main` post-merge sync (Steps 9 and 13). T-300 PR #226 "
        "round 2 caught the original `git pull origin main` form; "
        "regressing it would re-open the merge-commit-on-main hazard "
        'documented in CLAUDE.md "Deployment ordering".'
    )
    assert 'GH_TOKEN="$BOT_TOKEN" gh pr create' in body, (
        "close-wave SKILL.md Step 13 must show the bot-authenticated "
        'PR-creation form (`GH_TOKEN="$BOT_TOKEN" gh pr create ...`). '
        "Codex PR #230 round 1 MEDIUM caught an earlier draft that "
        "showed a bare `gh pr create` snippet; an operator following "
        "that literally would create the PR under their personal "
        "`gh auth` session and break the bot-identity invariant the "
        "github-bot skill exists to enforce."
    )


def test_close_wave_skill_step10_refetches_before_branching() -> None:
    """T-331: Step 10 must re-fetch and ff-only immediately before branching.

    Step 9 fast-forwards main, but Step 9.5 (make sync-mcp-dist) runs
    between Step 9 and Step 10. Any PR merged in that window silently
    invalidates Step 9's fast-forward, causing the close-wave branch to
    be created from a stale base. Codex then sees a branch whose base
    pre-dates the implementation merge and flags the work-log claims as
    false (observed on PR #242, T-327 close-wave for T-314).

    The fix is a mandatory re-fetch in Step 10's bash block, making the
    sequence fetch → ff-only → checkout -b appear *together* so the base
    is guaranteed fresh regardless of what merged during Steps 9.5+.
    """
    body = _read()
    step10_marker = "## Step 10: Open a close-wave branch"
    step11_marker = "## Step 10.5:"
    assert step10_marker in body, "Step 10 header missing from close-wave SKILL.md"
    step10_body = body[body.index(step10_marker) : body.index(step11_marker)]
    assert "git fetch origin" in step10_body, (
        "close-wave SKILL.md Step 10 must call `git fetch origin` "
        "immediately before creating the close-wave branch. Step 9 "
        "fetched main, but Step 9.5 runs between Step 9 and Step 10 "
        "and any PR merged in that window silently invalidates the "
        "fast-forward. Observed on PR #242 (T-327 close-wave for "
        "T-314): codex round 1 flagged 'the changes don't exist in "
        "the repo' because the branch base was pre-T-314."
    )
    assert "git merge --ff-only origin/main" in step10_body, (
        "close-wave SKILL.md Step 10 must call "
        "`git merge --ff-only origin/main` immediately before "
        "`git checkout -b wt-close-...`. Without it the branch base "
        "may be stale if a PR was merged during Step 9.5."
    )
    fetch_pos = step10_body.index("git fetch origin")
    ff_pos = step10_body.index("git merge --ff-only origin/main")
    branch_pos = step10_body.index("git checkout -b wt-close-")
    assert fetch_pos < ff_pos < branch_pos, (
        "close-wave SKILL.md Step 10 must order commands as: "
        "`git fetch origin` → `git merge --ff-only origin/main` → "
        "`git checkout -b wt-close-...`. The fetch and ff-only must "
        "appear *before* the branch creation so the branch base is "
        "always fresh."
    )
