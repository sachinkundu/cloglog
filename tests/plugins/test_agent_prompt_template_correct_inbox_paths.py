"""Pin: T-360 — agent-prompt template uses correct inbox paths.

The 2026-04-30 incident: T-353/T-356/T-358 AGENT_PROMPTs all hand-pasted
"Monitor your inbox at /home/sachin/code/cloglog/.cloglog/inbox" — the
*project root* inbox — instead of the *worktree* inbox. Three operator
retries to T-356 silently went to the wrong file and the agent sat idle
for 25 minutes.

The fix is structural — workflow rules now live in a single template
that every launch copies verbatim. These pins guard the load-bearing
distinction the template now codifies:

- Tail target = ``<WORKTREE_PATH>/.cloglog/inbox`` (worktree inbox).
- Lifecycle event write target = ``<PROJECT_ROOT>/.cloglog/inbox``
  (project root inbox, where the supervisor watches).

If a future edit collapses the two paths back to a single hard-coded
absolute path, the dedicated agent's tail will silently land on the
wrong file again. Pin both shapes so a directional rewrite is caught.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATE = REPO_ROOT / "plugins/cloglog/templates/AGENT_PROMPT.md"


def _read(p: Path) -> str:
    assert p.exists(), f"{p} missing — T-360 created this file"
    return p.read_text(encoding="utf-8")


def test_template_tails_worktree_inbox_not_project_root() -> None:
    body = _read(TEMPLATE)
    assert "tail -n 0 -F <WORKTREE_PATH>/.cloglog/inbox" in body, (
        "Template must instruct the agent to tail "
        "<WORKTREE_PATH>/.cloglog/inbox — NOT <PROJECT_ROOT>/.cloglog/inbox. "
        "The project-root inbox is for cross-agent / supervisor traffic; "
        "tailing it makes the worktree agent miss its own webhook events. "
        "(2026-04-30 incident: three agents silently sat idle on the wrong "
        "file for 25 minutes after operator retries.)"
    )


def test_template_writes_agent_started_to_project_root_inbox() -> None:
    """Lifecycle events the supervisor must see go to the project root,
    not the worktree inbox.

    ``agent_started`` is the canonical "I'm live" signal — if it lands
    on the worktree inbox, the supervisor never sees it and treats the
    launch as failed.
    """
    body = _read(TEMPLATE)
    # The write side appears in two forms (printf line + prose). The
    # prose form is the most stable to pin.
    assert "<PROJECT_ROOT>/.cloglog/inbox" in body, (
        "Template must mention <PROJECT_ROOT>/.cloglog/inbox as the "
        "write target for lifecycle events (agent_started, "
        "pr_merged_notification, agent_unregistered, mcp_unavailable, "
        "mcp_tool_error). Without this distinction, the supervisor "
        "stops seeing the worktree's lifecycle signals."
    )

    # Specifically: the agent_started printf line must target project root.
    # Find any printf with type=agent_started and ensure the redirect
    # target is the PROJECT_ROOT inbox.
    import re

    matches = re.findall(
        r'printf [\'"][^\'"]*"type":"agent_started"[^\'"]*[\'"].*?>>\s*(\S+)',
        body,
        flags=re.DOTALL,
    )
    assert matches, (
        "No agent_started printf line found in template; one must exist "
        "so agents have a copy-pasteable shape."
    )
    for target in matches:
        assert "<PROJECT_ROOT>" in target, (
            f"agent_started printf redirects to {target!r} — must redirect "
            "to <PROJECT_ROOT>/.cloglog/inbox so the supervisor sees the "
            "agent come alive."
        )


def test_template_does_not_hardcode_absolute_inbox_paths() -> None:
    """The template is copied verbatim into every worktree on every host;
    a hard-coded ``/home/sachin/...`` absolute path would mis-direct
    every agent on any other operator's machine.
    """
    body = _read(TEMPLATE)
    assert "/home/sachin/code/cloglog/.cloglog/inbox" not in body, (
        "Template must NOT hard-code an operator-host absolute inbox "
        "path — use <WORKTREE_PATH> / <PROJECT_ROOT> placeholders. The "
        "task.md sibling carries the resolved absolute paths."
    )
