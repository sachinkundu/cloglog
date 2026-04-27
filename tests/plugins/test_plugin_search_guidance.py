"""Backstop: T-309.

T-164 (PR #221) shipped ``mcp__cloglog__search`` which resolves any
entity-number reference to a UUID in one call. ``/cloglog launch``
itself only accepts ``T-*`` and ``F-*`` (epics have no launch
semantics — see Step 1b of the launch skill); the resolver tool is
broader than the workflow command's accepted input. The launch skill
is the canonical entry point for both the user-invoked
``/cloglog launch`` flow and the prompt template every spawned agent
inherits — if either surface still steers operators or agents at
``get_board``/``list_features`` for ID lookups, the team keeps
reaching for ``psql`` or paging the full board instead.

These pins assert by **presence**:

1. The user-facing Step 1b body cites ``mcp__cloglog__search`` as the
   resolver for entity-number references.
2. The agent-template ``ToolSearch(query: "select:...")`` preload list
   includes ``mcp__cloglog__search`` so spawned agents have the schema
   loaded before the first ``T-NNN`` reference appears in their inbox.

If a future paraphrase drops either, the next agent silently regresses
to a board page; that is exactly what this task closed.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LAUNCH_SKILL = REPO_ROOT / "plugins/cloglog/skills/launch/SKILL.md"


def _read(p: Path) -> str:
    assert p.exists(), f"{p} missing — fix the path or the file was moved"
    return p.read_text(encoding="utf-8")


def test_step_1b_body_recommends_search() -> None:
    body = _read(LAUNCH_SKILL)
    section = re.search(
        r"### 1b\. Resolve entity IDs\n(.*?)\n### 1c\.",
        body,
        flags=re.DOTALL,
    )
    assert section, "Step 1b section missing or its heading was renamed"
    snippet = section.group(1)
    assert "mcp__cloglog__search" in snippet, (
        "Step 1b must point operators at mcp__cloglog__search as the "
        "first move for resolving entity-number references — without "
        "it the next reader reaches for get_board or psql."
    )


def test_agent_template_toolsearch_preload_includes_search() -> None:
    body = _read(LAUNCH_SKILL)
    select_lists = re.findall(r"select:([^\"')]+)", body)
    assert select_lists, "No ToolSearch select: lists found in launch SKILL"
    assert any("mcp__cloglog__search" in lst for lst in select_lists), (
        "The agent-template ToolSearch preload must include "
        "mcp__cloglog__search so spawned agents can resolve "
        "entity-number references in one call instead of paging the "
        "board. Found select lists: " + " | ".join(select_lists)
    )
