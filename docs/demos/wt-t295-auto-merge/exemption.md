---
verdict: no_demo
diff_hash: a6221e639ef2e483d3d0c964103afd062f683e36e082024b1aa283d54a913b0c
classifier: demo-classifier
generated_at: 2026-04-26T10:30:36Z
---

## Why no demo

Diff is entirely plugin/agent workflow plumbing: new pure-Python helper at
`plugins/cloglog/scripts/auto_merge_gate.py`, design doc edits to
`docs/design/agent-lifecycle.md`, skill/agent-template prose updates
(github-bot, launch, worktree-agent), and pinning tests under `tests/`. No
HTTP route decorators, no React components, no MCP tool registrations in
`mcp-server/src/server.ts`, no CLI surface a user reads, no DB migration.
The strongest `needs_demo` candidate was the `auto_merge_gate.py` CLI, but
it is an internal worktree-agent helper invoked via shell from a skill — not
a user-invoked command — so `cli-exec` does not apply. If the diff had added
a new `@router` decorator wiring auto-merge into the gateway, or a new
`server.tool` registration in mcp-server, the verdict would have flipped to
`needs_demo`.

## Changed files

- docs/demos/wt-t295-auto-merge/exemption.md
- docs/design/agent-lifecycle.md
- plugins/cloglog/agents/worktree-agent.md
- plugins/cloglog/scripts/auto_merge_gate.py
- plugins/cloglog/skills/github-bot/SKILL.md
- plugins/cloglog/skills/launch/SKILL.md
- tests/plugins/test_auto_merge_skill_handles_silent_holds.py
- tests/test_auto_merge_gate.py
