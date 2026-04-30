"""Backstop: T-213.

The "Stop on MCP failure" rule must appear verbatim in every place an agent
or main-agent reader would reach for it. Keeping the canonical sentence
byte-exact across locations prevents the rule from drifting back to its
pre-T-213 "startup unavailability only" wording. The canonical source of
truth is ``docs/design/agent-lifecycle.md`` §4.1; the other files MUST
restate the same sentence and then link back to §4.1.

The backstop is intentionally narrow: it asserts the short canonical
sentence is present, not the entire surrounding paragraph. Expansion text
can evolve per venue; the rule statement cannot.

If this test fails, either:

* a file was edited and the canonical sentence was changed/removed — update
  all five files together, OR
* a new location for the rule was added — extend ``EXPECTED_LOCATIONS``
  below and update §4.1 to mention it.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

CANONICAL_RULE = (
    "Halt on any MCP failure: startup unavailability emits `mcp_unavailable` "
    "and exits; runtime tool errors emit `mcp_tool_error` and wait for the "
    "main agent; transient network errors get one backoff retry before "
    "escalating."
)

EXPECTED_LOCATIONS = (
    "docs/design/agent-lifecycle.md",
    "plugins/cloglog/templates/claude-md-fragment.md",
    "plugins/cloglog/templates/AGENT_PROMPT.md",
    "plugins/cloglog/skills/setup/SKILL.md",
    "CLAUDE.md",
)


def test_canonical_rule_appears_verbatim_in_each_location() -> None:
    missing: list[str] = []
    for rel in EXPECTED_LOCATIONS:
        path = REPO_ROOT / rel
        assert path.exists(), f"{rel} not found at {path}"
        body = path.read_text(encoding="utf-8")
        if CANONICAL_RULE not in body:
            missing.append(rel)
    assert not missing, (
        "Canonical T-213 rule missing from:\n  - "
        + "\n  - ".join(missing)
        + "\n\nExpected sentence:\n  "
        + CANONICAL_RULE
        + "\n\nSee docs/design/agent-lifecycle.md §4.1 for the authoritative wording."
    )


def test_mcp_tool_error_event_is_documented_in_agent_lifecycle() -> None:
    """The new event must have a shape definition in §4.1, not just a
    mention. Agents that emit it and main agents that consume it both read
    this file — missing shape means ambiguity."""
    spec = (REPO_ROOT / "docs/design/agent-lifecycle.md").read_text(encoding="utf-8")
    assert '"type": "mcp_tool_error"' in spec, (
        "agent-lifecycle.md §4.1 must include the mcp_tool_error event shape "
        "(JSON block with type/worktree/tool/error/reason fields). Without a "
        "pinned shape, emitters and consumers will diverge."
    )
    for required_field in ('"tool"', '"error"', '"worktree_id"', '"reason"'):
        assert required_field in spec, (
            f"agent-lifecycle.md mcp_tool_error shape missing field {required_field}"
        )


def test_outbound_events_table_distinguishes_unavailable_from_tool_error() -> None:
    """The Section 3 outbound events table must list BOTH events distinctly.
    Before T-213 only `mcp_unavailable` existed and covered 'any MCP
    failure'; the backstop here prevents a future edit from collapsing them
    back."""
    spec = (REPO_ROOT / "docs/design/agent-lifecycle.md").read_text(encoding="utf-8")
    assert "| `mcp_unavailable` |" in spec, (
        "agent-lifecycle.md outbound events table must still list mcp_unavailable"
    )
    assert "| `mcp_tool_error` |" in spec, (
        "agent-lifecycle.md outbound events table must list mcp_tool_error "
        "(added by T-213 to distinguish runtime failures from startup ones)"
    )
