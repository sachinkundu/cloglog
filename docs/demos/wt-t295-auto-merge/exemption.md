---
verdict: no_demo
diff_hash: 7351a0d3c53a123d5e2e225af2f9f849fff5122accc8cbd061b7a17b58b1c7a4
classifier: demo-classifier
generated_at: 2026-04-26T10:41:53Z
---

## Why no demo

Diff touches only agent-internal plumbing: docs
(`docs/design/agent-lifecycle.md`), worktree-agent/skill prompts
(`plugins/cloglog/agents/worktree-agent.md`,
`plugins/cloglog/skills/github-bot/SKILL.md`,
`plugins/cloglog/skills/launch/SKILL.md`), a new pure helper at
`plugins/cloglog/scripts/auto_merge_gate.py` invoked by agents via shell, and
two test files. No `@router.*` decorator changes in `src/**`, no React
components, no `server.tool` registrations in `mcp-server/`, no user-invoked
CLI surface, and no DB migrations. Strongest counter-signal considered was
the `auto_merge_gate.py` CLI-shaped helper, but its consumer is the
worktree-agent's bash, not a human reading stdout. If the change had added an
`@router.*` (e.g. exposing a merge-gate decision endpoint in
`src/gateway/`) or modified `mcp-server/src/server.ts` tool schemas, the
verdict would flip to `needs_demo`.

## Changed files

- docs/demos/wt-t295-auto-merge/exemption.md
- docs/design/agent-lifecycle.md
- plugins/cloglog/agents/worktree-agent.md
- plugins/cloglog/scripts/auto_merge_gate.py
- plugins/cloglog/skills/github-bot/SKILL.md
- plugins/cloglog/skills/launch/SKILL.md
- tests/plugins/test_auto_merge_skill_handles_silent_holds.py
- tests/test_auto_merge_gate.py
