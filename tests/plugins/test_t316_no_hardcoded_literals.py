"""T-316 pin tests — config-driven values must not appear as hard-coded
literals outside ``.cloglog/config.yaml``.

Phase 1 step 3 of the plugin-portability work hoists five cloglog-specific
strings out of the plugin tree and into config keys so a downstream project
can ship its own values without forking the plugin:

* ``reviewer_bot_logins`` — replaces ``cloglog-codex-reviewer[bot]`` and
  ``cloglog-opencode-reviewer[bot]`` in the github-bot/launch skills and
  the auto_merge_gate helper.
* ``dashboard_key`` — replaces ``cloglog-dashboard-dev`` in the demo skill.
* ``webhook_tunnel_name`` — replaces ``cloglog-webhooks`` in
  ``scripts/preflight.sh``.
* ``prod_worktree_path`` (already in config) — replaces ``cloglog-prod``
  prose in the close-wave skill.

Each pin below scopes to the specific files the audit calls out. Project
source under ``src/``, design docs under ``plugins/cloglog/docs/``, and
historical work-logs continue to reference cloglog identities — those are
genuine project context, not portability hazards.

The pins are absence-style: a future revert that re-introduces a literal
must trip them. Drift in either direction (renaming the constant in
config without retiring the call sites, or re-inlining a literal) loses
the portability guarantee, so the tests look at the actual on-disk
content of the call sites listed in the audit.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# ── reviewer bot logins ────────────────────────────────────────────────

_REVIEWER_BOT_LITERALS = (
    "cloglog-codex-reviewer[bot]",
    "cloglog-opencode-reviewer[bot]",
)

_REVIEWER_BOT_FILES = (
    "plugins/cloglog/skills/github-bot/SKILL.md",
    "plugins/cloglog/skills/launch/SKILL.md",
    "plugins/cloglog/scripts/auto_merge_gate.py",
)


@pytest.mark.parametrize("relpath", _REVIEWER_BOT_FILES)
@pytest.mark.parametrize("literal", _REVIEWER_BOT_LITERALS)
def test_no_reviewer_bot_literal(relpath: str, literal: str) -> None:
    body = (REPO_ROOT / relpath).read_text(encoding="utf-8")
    assert literal not in body, (
        f"{relpath} contains the literal {literal!r} — T-316 requires this "
        "value to live only in .cloglog/config.yaml: reviewer_bot_logins."
    )


# ── dashboard key ──────────────────────────────────────────────────────


def test_demo_skill_does_not_hardcode_dashboard_key() -> None:
    body = (REPO_ROOT / "plugins/cloglog/skills/demo/SKILL.md").read_text(encoding="utf-8")
    assert "cloglog-dashboard-dev" not in body, (
        "plugins/cloglog/skills/demo/SKILL.md must not hardcode the "
        "cloglog dashboard key — T-316 moved it to "
        ".cloglog/config.yaml: dashboard_key. Reference $DASHBOARD_KEY "
        "(loaded via the grep+sed reader the SKILL documents) instead."
    )


# ── webhook tunnel name ────────────────────────────────────────────────


_WEBHOOK_TUNNEL_FILES = (
    "scripts/preflight.sh",
    "plugins/cloglog/skills/github-bot/SKILL.md",
    "plugins/cloglog/skills/launch/SKILL.md",
    "plugins/cloglog/skills/demo/SKILL.md",
    "plugins/cloglog/skills/close-wave/SKILL.md",
)


@pytest.mark.parametrize("relpath", _WEBHOOK_TUNNEL_FILES)
def test_no_webhook_tunnel_name_literal(relpath: str) -> None:
    body = (REPO_ROOT / relpath).read_text(encoding="utf-8")
    assert "cloglog-webhooks" not in body, (
        f"{relpath} contains the literal 'cloglog-webhooks' — T-316 "
        "requires this value to live only in "
        ".cloglog/config.yaml: webhook_tunnel_name."
    )


# ── prod worktree path ────────────────────────────────────────────────


def test_close_wave_skill_does_not_hardcode_prod_worktree_path() -> None:
    body = (REPO_ROOT / "plugins/cloglog/skills/close-wave/SKILL.md").read_text(encoding="utf-8")
    assert "cloglog-prod" not in body, (
        "plugins/cloglog/skills/close-wave/SKILL.md must not hardcode "
        "'cloglog-prod' — T-316 requires it to reference "
        "`.cloglog/config.yaml: prod_worktree_path` instead so the prod "
        "worktree path is not a portability hazard."
    )


# ── config keys present ───────────────────────────────────────────────


def test_reviewer_bot_logins_excludes_stage_a_opencode() -> None:
    """T-316 codex round 2: auto-merge eligibility is final-stage-only.

    The two-stage review pipeline (``plugins/cloglog/docs/two-stage-pr-review.md``)
    runs opencode first (stage A) then codex (stage B). Only codex's ``:pass:``
    may auto-merge. Listing the opencode bot in ``reviewer_bot_logins`` would
    let a stage-A approval merge a PR before codex stage B runs — the exact
    failure mode codex flagged on PR #255 round 2. This pin keeps the
    auto-merge-eligible set scoped to final-stage reviewers, regardless of
    how the surrounding two-stage docs evolve.
    """
    body = (REPO_ROOT / ".cloglog/config.yaml").read_text(encoding="utf-8")
    # Locate the reviewer_bot_logins block and assert opencode isn't in it.
    in_block = False
    block_lines: list[str] = []
    for raw in body.splitlines():
        if not in_block:
            if raw.startswith("reviewer_bot_logins:"):
                in_block = True
            continue
        if raw and not raw[0:1].isspace() and not raw.lstrip().startswith("#"):
            break
        block_lines.append(raw)
    block = "\n".join(block_lines)
    assert "cloglog-opencode-reviewer" not in block, (
        "cloglog-opencode-reviewer[bot] is listed in reviewer_bot_logins. "
        "Stage-A reviewers must not appear in the auto-merge-eligible set — "
        "see plugins/cloglog/docs/two-stage-pr-review.md and the github-bot "
        "skill's `Auto-Merge on Codex Pass` section. List only stage-B "
        "(final-stage) reviewer bots here."
    )


def test_config_yaml_carries_the_new_keys() -> None:
    """Smoke pin: ``.cloglog/config.yaml`` continues to carry every key
    introduced by T-316. Catches an accidental key rename that would leave
    every consumer reading an empty value (and silently auto-exempting the
    demo gate, or matching no reviewer)."""
    body = (REPO_ROOT / ".cloglog/config.yaml").read_text(encoding="utf-8")
    for key in (
        "reviewer_bot_logins:",
        "dashboard_key:",
        "webhook_tunnel_name:",
        "demo_allowlist_paths:",
    ):
        assert key in body, f".cloglog/config.yaml is missing the {key!r} key required by T-316."
