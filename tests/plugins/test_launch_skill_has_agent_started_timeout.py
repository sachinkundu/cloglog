"""Pin tests: T-356.

The main agent must detect failed worktree-agent launches by waiting for an
``agent_started`` event on ``<project_root>/.cloglog/inbox`` with a deadline
(``launch_confirm_timeout_seconds``, default ``90``). On timeout the launch
SKILL emits a diagnostic checklist (``query-tab-names``, ``bash -n``,
``agent-shutdown-debug.log``, ``.env``) and hands off to the operator —
**no silent retry**. The same deadline applies to supervisor relaunches.

Pin shape:
  1. Step 5 (Verification) mentions ``agent_started``, the literal config
     key ``launch_confirm_timeout_seconds``, the default ``90``, and at
     least the four diagnostic-checklist items.
  2. The Supervisor Relaunch Flow section also mentions ``agent_started``
     and the deadline — both call sites pinned.
  3. Absence-pin: the SKILL must NOT contain imperative-retry phrasing
     ("retry up to N times", "silently retry"). The SKILL is allowed to
     describe the antipattern in prose; the absence-pin matches only an
     imperative form.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LAUNCH_SKILL = REPO_ROOT / "plugins/cloglog/skills/launch/SKILL.md"
SETUP_SKILL = REPO_ROOT / "plugins/cloglog/skills/setup/SKILL.md"

DIAGNOSTIC_TOKENS = (
    "query-tab-names",
    "bash -n",
    "agent-shutdown-debug.log",
    ".env",
)


def _read(p: Path) -> str:
    assert p.exists(), f"{p} missing"
    return p.read_text(encoding="utf-8")


def _section(body: str, heading_pattern: str) -> str:
    """Extract a SKILL.md section by heading regex up to the next ``## `` heading."""
    match = re.search(rf"({heading_pattern}.*?)(?=\n## [^\n]|\Z)", body, flags=re.DOTALL)
    assert match, f"section matching {heading_pattern!r} missing from launch SKILL.md"
    return match.group(1)


def test_step5_pins_agent_started_deadline_and_diagnostic_checklist() -> None:
    body = _read(LAUNCH_SKILL)
    step5 = _section(body, r"## Step 5: Verification")

    assert "agent_started" in step5, (
        "Step 5 must mention `agent_started` — the only authoritative "
        "liveness signal for a launched worktree agent (T-356)."
    )
    assert "launch_confirm_timeout_seconds" in step5, (
        "Step 5 must reference the `launch_confirm_timeout_seconds` config "
        "key so operators can tune the deadline (T-356)."
    )
    assert re.search(r"(?<!\d)90(?!\d)", step5), (
        "Step 5 must document the default deadline of 90 seconds (T-356)."
    )
    for token in DIAGNOSTIC_TOKENS:
        assert token in step5, (
            f"Step 5 diagnostic checklist missing {token!r} — operators need "
            "every probe (tab present, syntax valid, trap fire, env set) to "
            "triage a launch failure (T-356)."
        )


def test_supervisor_relaunch_flow_pins_same_deadline() -> None:
    body = _read(LAUNCH_SKILL)
    section = _section(body, r"## Supervisor Relaunch Flow")

    assert "agent_started" in section, (
        "Supervisor Relaunch Flow must mention `agent_started` — a "
        "continuation prompt can trip the same bootstrap failures as an "
        "initial launch (T-356)."
    )
    assert "launch_confirm_timeout_seconds" in section, (
        "Supervisor Relaunch Flow must reference `launch_confirm_timeout_seconds` "
        "so the same deadline applies on both call sites (T-356)."
    )
    assert re.search(r"(?<!\d)90(?!\d)", section), (
        "Supervisor Relaunch Flow must document the default deadline of 90 seconds (T-356)."
    )


def test_setup_skill_handle_agent_unregistered_mirrors_relaunch_contract() -> None:
    """Codex round 1 (HIGH): the supervisor's setup SKILL `Handle
    agent_unregistered` section must mirror the launch SKILL's relaunch
    contract — same `agent_started` deadline, same diagnostic checklist,
    same operator handoff. Without this, a supervisor following the setup
    SKILL relaunches a worktree and assumes liveness with no deadline,
    re-introducing the silent-hang T-356 closes.
    """
    body = _read(SETUP_SKILL)
    section = _section(body, r"### Handle `agent_unregistered`")

    assert "agent_started" in section, (
        "setup SKILL Handle agent_unregistered must mirror the launch "
        "SKILL's `agent_started` confirmation contract on relaunch (T-356)."
    )
    assert "launch_confirm_timeout_seconds" in section, (
        "setup SKILL relaunch must reference `launch_confirm_timeout_seconds` — "
        "same deadline as the launch SKILL's call sites (T-356)."
    )
    assert re.search(r"(?<!\d)90(?!\d)", section), (
        "setup SKILL relaunch must document the 90s default deadline (T-356)."
    )


def test_diagnostic_checklist_does_not_probe_env_for_api_key() -> None:
    """Codex round 1 (MEDIUM): `CLOGLOG_API_KEY` MUST NOT be probed inside
    `<worktree>/.env`. The launcher's `_api_key` resolves env first, then
    `~/.cloglog/credentials`; `.env` is not on the resolution path and
    `tests/test_mcp_json_no_secret.py` pins the invariant. A combined
    probe (`grep -E 'CLOGLOG_API_KEY|DATABASE_URL' <worktree>/.env`)
    encodes the opposite of the runtime contract and would push operators
    toward a secret-placement violation.

    Absence-pin uses an executable-form regex (the actual probe shape) so
    that *prose* explaining the antipattern doesn't trip the test —
    consistent with CLAUDE.md "Absence-pins on antipattern substrings
    collide with documentation that names the antipattern".
    """
    forbidden_probe = re.compile(r"grep\s+-E?\s*['\"]\s*CLOGLOG_API_KEY\s*\|\s*DATABASE_URL")
    for path in (LAUNCH_SKILL, SETUP_SKILL, REPO_ROOT / "CLAUDE.md"):
        text = _read(path)
        match = forbidden_probe.search(text)
        assert match is None, (
            f"{path.relative_to(REPO_ROOT)} must NOT probe `CLOGLOG_API_KEY` "
            f"in `<worktree>/.env`. The key lives in env or "
            "`~/.cloglog/credentials` (T-356 codex round 1). Probe each "
            f"credential at its real source. Found: {match.group(0)!r}"
        )


def test_skill_does_not_prescribe_imperative_silent_retry() -> None:
    """Absence-pin against imperative-retry phrasing.

    The SKILL is allowed (and expected) to *describe* the antipattern in
    prose ("the main agent does NOT silently retry"). The pin matches only
    the imperative shape, so prose explanations of the antipattern do not
    trip it. Per CLAUDE.md "Absence-pins on antipattern substrings collide
    with documentation that names the antipattern" — phrase the absence-pin
    as a regex against an imperative form.
    """
    body = _read(LAUNCH_SKILL)
    # Imperative-retry shapes the SKILL must not adopt:
    #   "retry up to N times" / "retry up to <N> times"
    #   "loop on the launch up to" (with a numeric bound)
    forbidden_patterns = [
        r"retry up to \d+ time",
        r"silently retry up to",
        r"loop the launch up to \d+",
    ]
    offenders = [pat for pat in forbidden_patterns if re.search(pat, body, flags=re.IGNORECASE)]
    assert not offenders, (
        "Launch SKILL must NOT prescribe imperative silent retry — the "
        "operator owns the call on a launch-confirm timeout (T-356). "
        f"Found imperative-retry shapes: {offenders}"
    )
