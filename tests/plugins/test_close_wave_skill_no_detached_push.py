"""Backstop: T-301 / T-prod-7 / T-395.

The close-wave skill historically committed fold/reconcile updates
in-place on the main clone (detached HEAD) and pushed via the bot to a
`wt-close-*` branch — a workaround for the dev worktree's inability to
sit on local `main`. Post-T-300 the dev clone has a writable local
`main`, and close-wave moved to the standard `wt-close-<date>-<wave>`
branch + PR flow (see `docs/design/prod-branch-tracking.md` §7).

T-395 then retired the branch + PR flow entirely: the wave-fold commit
goes directly to `main` with `ALLOW_MAIN_COMMIT=1` and the bot's push
token, bypassing codex review of what is effectively a docs-only commit.

These pin tests assert:
- *Absence* of the two retired patterns (detached-HEAD push, chore-close- prefix).
- *Absence* of a `wt-close-*` branch or a close-wave PR.
- *Presence* of the new direct-to-main commit and bot-push patterns.
- *Presence* of the pre-commit re-fetch that guards the commit window.

Per the codebase's leak-after-fix rule, absence asserts are the only way
to catch a future revert that re-introduces a retired pattern — the bug
looked correct in tests because the workaround "worked", the cost was
integration-flow rot, not a unit-test failure.
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
        "T-prod-7 retired."
    )


def test_close_wave_skill_does_not_use_chore_close_branch_prefix() -> None:
    body = _read()
    assert "chore-close-" not in body, (
        "close-wave SKILL.md must not reference the legacy `chore-close-` "
        "branch prefix. The current convention is a direct commit to "
        "`main` (Step 13); there is no close-wave branch."
    )


def test_close_wave_skill_does_not_create_wt_close_branch() -> None:
    body = _read()
    assert "git checkout -b wt-close-" not in body, (
        "close-wave SKILL.md must not create a `wt-close-*` branch. "
        "T-395 retired the branch + PR flow: the wave-fold commit goes "
        "directly to `main` with ALLOW_MAIN_COMMIT=1. Re-introducing "
        "the branch would restore the full codex-review round-trip for "
        "a docs-only commit, which is what T-395 was filed to eliminate."
    )


def test_close_wave_skill_does_not_open_pr_for_wave_log() -> None:
    body = _read()
    assert "gh pr create --base main --head wt-close-" not in body, (
        "close-wave SKILL.md must not open a PR for the wave work log. "
        "T-395 retired the wave-PR flow: the fold commit pushes directly "
        "to `main`, bypassing codex review of what is effectively a "
        "docs-only commit. Re-introducing `gh pr create` for the "
        "wave log would restore the full review round-trip T-395 removed."
    )


def test_close_wave_skill_commits_directly_to_main() -> None:
    body = _read()
    assert "ALLOW_MAIN_COMMIT=1 git commit" in body, (
        "close-wave SKILL.md Step 13 must show the `ALLOW_MAIN_COMMIT=1 "
        "git commit` command for the direct-to-main fold commit. Without "
        "this, the dev-clone pre-commit hook (install-dev-hooks.sh) would "
        "reject the commit with no escape hatch visible to the operator."
    )


def test_close_wave_skill_pushes_to_main_via_bot() -> None:
    body = _read()
    assert "main:main" in body, (
        "close-wave SKILL.md Step 13 must push via `git push ... main:main` "
        "to push directly to the remote main branch using the bot identity. "
        "The wave-fold commit must go to main, not to a wt-close-* branch."
    )
    assert "BOT_TOKEN" in body, (
        "close-wave SKILL.md Step 13 must use the bot token for the push. "
        "A bare `git push` or push under the operator's personal gh auth "
        "breaks the bot-identity invariant."
    )


def test_close_wave_skill_refetches_before_direct_commit() -> None:
    """T-395: Step 10 must re-fetch and ff-only immediately before committing.

    Step 9 fast-forwards main, but Step 9.5 (make sync-mcp-dist) runs
    between Step 9 and Step 10. Any PR merged in that window silently
    invalidates Step 9's fast-forward, causing the direct commit to push
    to a stale base. The fix is a mandatory re-fetch in Step 10.
    """
    body = _read()
    step10_marker = "## Step 10: Fetch and prepare for direct commit to main"
    step105_marker = "## Step 10.5:"
    assert step10_marker in body, "Step 10 header missing from close-wave SKILL.md"
    step10_body = body[body.index(step10_marker) : body.index(step105_marker)]
    assert "git fetch origin" in step10_body, (
        "close-wave SKILL.md Step 10 must call `git fetch origin` "
        "immediately before the direct-to-main commit. Step 9 "
        "fetched main, but Step 9.5 runs between Step 9 and Step 10 "
        "and any PR merged in that window silently invalidates the "
        "fast-forward."
    )
    assert "git merge --ff-only origin/main" in step10_body, (
        "close-wave SKILL.md Step 10 must call "
        "`git merge --ff-only origin/main` immediately before "
        "committing. Without it the local main may be stale."
    )
    fetch_pos = step10_body.index("git fetch origin")
    ff_pos = step10_body.index("git merge --ff-only origin/main")
    assert fetch_pos < ff_pos, (
        "close-wave SKILL.md Step 10 must order: "
        "`git fetch origin` before `git merge --ff-only origin/main`."
    )


def test_close_wave_skill_keeps_ff_only_in_quality_gate_area() -> None:
    """Step 9 still does a fetch + ff-only; the SKILL must not regress
    the merge-commit-on-main hazard documented in CLAUDE.md."""
    body = _read()
    assert "git merge --ff-only origin/main" in body, (
        "close-wave SKILL.md must keep `git merge --ff-only "
        "origin/main` (Steps 9 and 10). T-300 PR #226 round 2 caught "
        "the original `git pull origin main` form; regressing it would "
        "re-open the merge-commit-on-main hazard documented in CLAUDE.md."
    )
