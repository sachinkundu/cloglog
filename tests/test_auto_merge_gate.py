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


def _green_checks() -> list[dict]:
    return [
        {"name": "quality", "bucket": "pass"},
        {"name": "frontend", "bucket": "pass"},
    ]


def _inputs(**overrides):
    base = dict(
        reviewer=gate.CODEX_BOT_LOGIN,
        body=":pass: codex — session 2/5 — no further concerns",
        checks=_green_checks(),
        labels=["enhancement"],
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


def test_empty_check_list_blocks() -> None:
    """No rollup yet → treat as not-green; the gate must wait for CI."""
    decision = gate.should_auto_merge(_inputs(checks=[]))
    assert decision.merge is False
    assert decision.reason == "ci_not_green"


def test_cancelled_ci_check_blocks() -> None:
    decision = gate.should_auto_merge(_inputs(checks=[{"name": "quality", "bucket": "cancel"}]))
    assert decision.merge is False
    assert decision.reason == "ci_not_green"


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
        "reviewer": gate.CODEX_BOT_LOGIN,
        "body": ":pass: ok",
        "checks": _green_checks(),
        "labels": [],
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    rc = gate.main([])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "merge"


def test_cli_exits_one_on_hold(monkeypatch, capsys) -> None:
    payload = {
        "reviewer": gate.CODEX_BOT_LOGIN,
        "body": ":pass: ok",
        "checks": _green_checks(),
        "labels": [gate.HOLD_LABEL],
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    rc = gate.main([])
    assert rc == 1
    assert capsys.readouterr().out.strip() == "hold_label"


def test_cli_handles_missing_optional_fields(monkeypatch, capsys) -> None:
    """Defensive: missing ``labels`` / ``checks`` must not crash — they default
    to empty, which holds with ``ci_not_green``."""
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(json.dumps({"reviewer": gate.CODEX_BOT_LOGIN, "body": ":pass:"})),
    )
    rc = gate.main([])
    assert rc == 1
    assert capsys.readouterr().out.strip() == "ci_not_green"
