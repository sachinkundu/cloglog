---
verdict: no_demo
diff_hash: b4a07f4653d48cc769b72b6ca4b3958969246c658110bf38ff5ad725bfcc2874
classifier: demo-classifier
generated_at: 2026-04-26T13:00:00Z
---

## Why no demo

Round-2 diff is doc/protocol propagation:
`plugins/cloglog/{skills,agents,templates,hooks}` updates,
`docs/design/agent-lifecycle.md`, two test files, and a string-only edit
to `src/board/templates.py` expanding the close-worktree task description.

No new or changed `@router.*` decorators in `src/**`, no
`frontend/src/**` changes, no `server.tool()` registrations in
`mcp-server/src/server.ts`, and no user-facing CLI output. The hook
change enriches an internal main-inbox event (`agent_unregistered`
`prs` map) consumed by other agents, not stakeholders.

Counterfactual: had the `prs` map been surfaced via a new gateway
endpoint or rendered in the React board, that would have flipped to
`needs_demo`.

## Round 1 vs Round 2

Round 1 (`diff_hash: 1e39f6f…`) covered the launch SKILL prompt,
agent-shutdown.sh hook, agent-lifecycle.md spec, board templates, and
two new tests. Round 2 (this exemption) adds the secondary-instruction
propagation Codex flagged — github-bot SKILL, claude-md-fragment,
worktree-agent — plus the cross-doc pin test. Same protocol change, no
new user-facing surface.

## Changed files

- docs/design/agent-lifecycle.md
- plugins/cloglog/agents/worktree-agent.md
- plugins/cloglog/hooks/agent-shutdown.sh
- plugins/cloglog/skills/github-bot/SKILL.md
- plugins/cloglog/skills/launch/SKILL.md
- plugins/cloglog/templates/claude-md-fragment.md
- src/board/templates.py
- tests/test_agent_lifecycle_pr_signals.py
- tests/test_agent_shutdown_hook.py
