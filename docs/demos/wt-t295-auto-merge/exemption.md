---
verdict: no_demo
diff_hash: 3081bc8cb127bb31425c57c74637f36d3a1ea25e74a6b947f994a2ec7c4fc5f0
classifier: demo-classifier
generated_at: 2026-04-26T10:23:45Z
---

## Why no demo

Diff is internal workflow plumbing for the worktree-agent's auto-merge gate
(T-295): a new pure-Python helper at `plugins/cloglog/scripts/auto_merge_gate.py`,
prose updates to `docs/design/agent-lifecycle.md` and the
github-bot/launch/worktree-agent skill markdowns, and two pin tests under
`tests/`. Strongest `needs_demo` candidate considered: the helper script is
invoked via a CLI shape, but it is agent-internal tooling (worktree-agent
shells out to it inside an event handler) — no user reads its stdout, no
`@router` decorator, no React component, no MCP `server.tool` registration,
no migration. Counterfactual: if the gate had added a new HTTP endpoint (e.g.,
a `/api/v1/auto-merge` route) or a new MCP tool wrapping the merge action,
or surfaced a `hold-merge` status dot in the dashboard, the verdict would
have flipped to `needs_demo`.

## Changed files

- docs/demos/wt-t295-auto-merge/exemption.md
- docs/design/agent-lifecycle.md
- plugins/cloglog/agents/worktree-agent.md
- plugins/cloglog/scripts/auto_merge_gate.py
- plugins/cloglog/skills/github-bot/SKILL.md
- plugins/cloglog/skills/launch/SKILL.md
- tests/plugins/test_auto_merge_skill_handles_silent_holds.py
- tests/test_auto_merge_gate.py
