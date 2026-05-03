"""Pin the auto-merge gate decision table (T-295).

The gate lives at ``plugins/cloglog/scripts/auto_merge_gate.py``. Worktree
agents shell out to it after a ``review_submitted`` inbox event to decide
whether to run ``gh pr merge --squash --delete-branch`` on their own PR.

These tests pin the four-condition truth table in the module docstring.
Loosening any condition without touching this file is a red flag.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "plugins" / "cloglog" / "scripts" / "auto_merge_gate.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("auto_merge_gate", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


gate = _load_module()

# Hermetic reviewer-bot list — must NOT be the cloglog-specific literal so the
# test stays portable when the plugin is consumed by a non-cloglog project
# (T-316). The gate's ``reviewer_bot_logins`` field on ``GateInputs`` is the
# injection seam that keeps the pure logic decoupled from
# ``.cloglog/config.yaml`` lookup.
_TEST_REVIEWER_BOTS = ("test-reviewer[bot]",)
_TEST_REVIEWER = _TEST_REVIEWER_BOTS[0]


def _green_checks() -> list[dict]:
    return [
        {"name": "quality", "bucket": "pass"},
        {"name": "frontend", "bucket": "pass"},
    ]


def _inputs(**overrides):
    base = dict(
        reviewer=_TEST_REVIEWER,
        body=":pass: codex — session 2/5 — no further concerns",
        checks=_green_checks(),
        labels=["enhancement"],
        has_human_changes_requested=False,
        mergeable_state="CLEAN",
        reviewer_bot_logins=_TEST_REVIEWER_BOTS,
    )
    base.update(overrides)
    return gate.GateInputs(**base)


# ── happy path ────────────────────────────────────────────────────────


def test_codex_pass_plus_green_ci_plus_no_hold_label_merges() -> None:
    decision = gate.should_auto_merge(_inputs())
    assert decision.merge is True
    assert decision.reason == "merge"


def test_skipping_buckets_count_as_green() -> None:
    """A workflow excluded by ``paths:`` reports ``skipping`` — must not block."""
    decision = gate.should_auto_merge(
        _inputs(
            checks=[
                {"name": "quality", "bucket": "pass"},
                {"name": "frontend", "bucket": "skipping"},
            ]
        )
    )
    assert decision.merge is True


# ── hold conditions ───────────────────────────────────────────────────


def test_non_codex_reviewer_blocks() -> None:
    decision = gate.should_auto_merge(_inputs(reviewer="sachinkundu"))
    assert decision.merge is False
    assert decision.reason == "not_codex_reviewer"


def test_codex_review_without_pass_marker_blocks() -> None:
    decision = gate.should_auto_merge(_inputs(body=":warning: codex — found a high-severity issue"))
    assert decision.merge is False
    assert decision.reason == "not_codex_pass"


def test_human_changes_requested_blocks_even_with_codex_pass() -> None:
    """A human ``CHANGES_REQUESTED`` review must override a codex ``:pass:``.

    Codex always posts as ``event="COMMENT"`` (see ``post_review`` in
    ``src/gateway/review_engine.py``), so its approval does not clear a
    human's outstanding change request from GitHub's side. The gate has to
    enforce the same rule the GitHub merge button does — otherwise the agent
    would auto-merge work the human explicitly blocked.
    """
    decision = gate.should_auto_merge(_inputs(has_human_changes_requested=True))
    assert decision.merge is False
    assert decision.reason == "human_changes_requested"


def test_human_changes_requested_blocks_before_label_or_ci() -> None:
    """Human block is the strongest hold — fires before label and CI checks."""
    decision = gate.should_auto_merge(
        _inputs(
            has_human_changes_requested=True,
            labels=[gate.HOLD_LABEL],
            checks=[],
        )
    )
    assert decision.reason == "human_changes_requested"


def test_hold_merge_label_blocks_even_with_pass_and_green_ci() -> None:
    decision = gate.should_auto_merge(_inputs(labels=["enhancement", gate.HOLD_LABEL]))
    assert decision.merge is False
    assert decision.reason == "hold_label"


def test_failing_ci_check_blocks() -> None:
    decision = gate.should_auto_merge(
        _inputs(
            checks=[
                {"name": "quality", "bucket": "pass"},
                {"name": "frontend", "bucket": "fail"},
            ]
        )
    )
    assert decision.merge is False
    assert decision.reason == "ci_not_green"


def test_pending_ci_check_blocks() -> None:
    decision = gate.should_auto_merge(
        _inputs(
            checks=[
                {"name": "quality", "bucket": "pass"},
                {"name": "frontend", "bucket": "pending"},
            ]
        )
    )
    assert decision.merge is False
    assert decision.reason == "ci_not_green"


def test_empty_check_list_treated_as_green() -> None:
    """Docs-only PRs have no CI configured (paths filter in ci.yml).

    The previous "empty = not green" interpretation deadlocked spec PRs
    that touch only ``docs/**`` — `gh pr checks --watch` returns
    immediately with no rollup and the gate would never advance. Codex
    flagged this on PR #224 round 3.
    """
    decision = gate.should_auto_merge(_inputs(checks=[]))
    assert decision.merge is True
    assert decision.reason == "merge"


def test_cancelled_ci_check_blocks() -> None:
    decision = gate.should_auto_merge(_inputs(checks=[{"name": "quality", "bucket": "cancel"}]))
    assert decision.merge is False
    assert decision.reason == "ci_not_green"


# ── merge conflict detection (T-362) ──────────────────────────────────


def test_dirty_merge_state_blocks_with_pr_dirty_reason() -> None:
    """A sibling PR landing first leaves this PR's mergeStateStatus DIRTY.

    GitHub does not webhook the affected PR when conflicts emerge from
    someone else's merge, so the agent's own ``gh pr view`` lookup at
    gate-evaluation time is the only signal. The gate must surface this
    as ``pr_dirty`` so the agent falls into the conflict-resolve flow
    instead of attempting a merge GitHub will reject.
    """
    decision = gate.should_auto_merge(_inputs(mergeable_state="DIRTY"))
    assert decision.merge is False
    assert decision.reason == "pr_dirty"


def test_dirty_blocks_before_ci_not_green() -> None:
    """``pr_dirty`` must fire before ``ci_not_green``.

    Otherwise a DIRTY PR with pending CI would block on
    ``gh pr checks --watch`` waiting for a result that cannot help —
    GitHub has already disabled the merge button. Resolving the conflict
    + pushing restarts CI anyway.
    """
    decision = gate.should_auto_merge(
        _inputs(
            mergeable_state="DIRTY",
            checks=[{"name": "quality", "bucket": "pending"}],
        )
    )
    assert decision.reason == "pr_dirty"


def test_clean_merge_state_does_not_block() -> None:
    decision = gate.should_auto_merge(_inputs(mergeable_state="CLEAN"))
    assert decision.merge is True


def test_unknown_merge_state_does_not_block() -> None:
    """``UNKNOWN`` is GitHub's transient state while it recomputes mergeability.

    Treating it as a hold would deadlock every PR for the seconds-to-minutes
    window after a sibling merge while GitHub catches up. The agent retries
    the lookup on the next gate evaluation.
    """
    decision = gate.should_auto_merge(_inputs(mergeable_state="UNKNOWN"))
    assert decision.merge is True


def test_empty_merge_state_does_not_block() -> None:
    """Older payload shape that omits ``mergeable_state`` must not regress."""
    decision = gate.should_auto_merge(_inputs(mergeable_state=""))
    assert decision.merge is True


def test_blocked_merge_state_does_not_match_pr_dirty() -> None:
    """``BLOCKED`` is a GitHub branch-protection hold, not a merge conflict.

    The conflict-resolve flow (``git merge origin/main``) would not
    unblock it. Only ``DIRTY`` triggers the conflict path; other states
    fall through to the existing CI / label / approval semantics.
    """
    decision = gate.should_auto_merge(_inputs(mergeable_state="BLOCKED"))
    assert decision.merge is True
    assert decision.reason == "merge"


def test_cli_propagates_dirty_merge_state(monkeypatch, capsys) -> None:
    payload = {
        "reviewer": _TEST_REVIEWER,
        "body": ":pass: ok",
        "checks": _green_checks(),
        "labels": [],
        "mergeable_state": "DIRTY",
        "reviewer_bot_logins": list(_TEST_REVIEWER_BOTS),
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    rc = gate.main([])
    assert rc == 1
    assert capsys.readouterr().out.strip() == "pr_dirty"


# ── ordering: cheap checks first ──────────────────────────────────────


def test_non_codex_reviewer_short_circuits_before_ci_lookup() -> None:
    """Random commenter → ``not_codex_reviewer`` even if everything else is wrong.

    The cheap reviewer check returns first so a noisy comment thread does not
    pay the cost of (and conceal) a CI inspection.
    """
    decision = gate.should_auto_merge(
        _inputs(
            reviewer="sachinkundu",
            body="lgtm",
            checks=[],
            labels=[gate.HOLD_LABEL],
        )
    )
    assert decision.reason == "not_codex_reviewer"


# ── pass-marker robustness ────────────────────────────────────────────


def test_pass_marker_tolerates_leading_whitespace() -> None:
    """Mirrors ``latest_codex_review_is_approval``: lstrip then startswith."""
    decision = gate.should_auto_merge(
        _inputs(body="\n  :pass: codex — session 1/5 — no further concerns")
    )
    assert decision.merge is True


def test_pass_marker_substring_does_not_match() -> None:
    """``:pass:`` must be the leading token, not anywhere in the body."""
    decision = gate.should_auto_merge(_inputs(body=":warning: contains :pass: somewhere later"))
    assert decision.merge is False
    assert decision.reason == "not_codex_pass"


# ── CLI ───────────────────────────────────────────────────────────────


def test_cli_exits_zero_on_merge(monkeypatch, capsys) -> None:
    payload = {
        "reviewer": _TEST_REVIEWER,
        "body": ":pass: ok",
        "checks": _green_checks(),
        "labels": [],
        "reviewer_bot_logins": list(_TEST_REVIEWER_BOTS),
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    rc = gate.main([])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "merge"


def test_cli_exits_one_on_hold(monkeypatch, capsys) -> None:
    payload = {
        "reviewer": _TEST_REVIEWER,
        "body": ":pass: ok",
        "checks": _green_checks(),
        "labels": [gate.HOLD_LABEL],
        "reviewer_bot_logins": list(_TEST_REVIEWER_BOTS),
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    rc = gate.main([])
    assert rc == 1
    assert capsys.readouterr().out.strip() == "hold_label"


def test_cli_handles_missing_optional_fields(monkeypatch, capsys) -> None:
    """Defensive: missing ``labels`` / ``checks`` / ``has_human_changes_requested``
    must not crash. Empty checks now count as green (docs-only PRs have no
    CI configured), and ``has_human_changes_requested`` defaults to False —
    so the minimal payload merges. The CLI's job here is to not crash; the
    decision-table tests above pin the actual semantics."""
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(
            json.dumps(
                {
                    "reviewer": _TEST_REVIEWER,
                    "body": ":pass:",
                    "reviewer_bot_logins": list(_TEST_REVIEWER_BOTS),
                }
            )
        ),
    )
    rc = gate.main([])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "merge"


def test_cli_propagates_human_changes_requested(monkeypatch, capsys) -> None:
    payload = {
        "reviewer": _TEST_REVIEWER,
        "body": ":pass: ok",
        "checks": _green_checks(),
        "labels": [],
        "has_human_changes_requested": True,
        "reviewer_bot_logins": list(_TEST_REVIEWER_BOTS),
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    rc = gate.main([])
    assert rc == 1
    assert capsys.readouterr().out.strip() == "human_changes_requested"


def test_cli_loads_reviewer_bot_logins_from_config_when_payload_omits_it(
    monkeypatch, capsys, tmp_path
) -> None:
    """When the JSON payload does not carry ``reviewer_bot_logins``, the gate
    walks up from CWD looking for ``.cloglog/config.yaml`` and reads the
    list. This pins the production invocation shape from
    ``plugins/cloglog/skills/github-bot/SKILL.md`` — the agent ships only
    PR-shape fields in the payload and lets the helper consult the
    project's config.
    """
    cfg_dir = tmp_path / ".cloglog"
    cfg_dir.mkdir()
    (cfg_dir / "config.yaml").write_text("reviewer_bot_logins:\n  - injected-via-config[bot]\n")
    monkeypatch.setenv("CLOGLOG_CONFIG_YAML", str(cfg_dir / "config.yaml"))
    payload = {
        "reviewer": "injected-via-config[bot]",
        "body": ":pass:",
        "checks": _green_checks(),
        "labels": [],
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    rc = gate.main([])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "merge"


def test_load_reviewer_bot_logins_returns_empty_when_no_config(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CLOGLOG_CONFIG_YAML", str(tmp_path / "missing.yaml"))
    assert gate._load_reviewer_bot_logins() == ()
