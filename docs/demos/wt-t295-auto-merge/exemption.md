---
verdict: no_demo
diff_hash: 26b021c9d0c22e8126fb78bd7773aee2a30ab78e6999c38f10b1fac1e5972d08
classifier: demo-classifier
generated_at: 2026-04-26T09:50:46Z
---

## Why no demo

Diff is internal plumbing for the worktree-agent auto-merge gate (T-295): a new
pure-Python helper at `plugins/cloglog/scripts/auto_merge_gate.py` with a
pinning test at `tests/test_auto_merge_gate.py`, plus skill/doc updates in
`plugins/cloglog/skills/{github-bot,launch}/SKILL.md` and
`docs/design/agent-lifecycle.md`. No HTTP route decorators (no `@router.*`
added in `src/**`), no React/UI changes, no MCP server.tool registrations, no
CLI stdout a human reads, no migrations. The strongest `needs_demo` candidate
considered was the new helper script's CLI, but it's invoked by agent skills,
not read by a stakeholder. Counterfactual: had the change added a new
`@router.post` in `src/gateway/**` to expose auto-merge state, or modified
`mcp-server/src/server.ts` tool schemas, the verdict would have flipped to
`needs_demo`.

## Changed files

- docs/design/agent-lifecycle.md
- plugins/cloglog/scripts/auto_merge_gate.py
- plugins/cloglog/skills/github-bot/SKILL.md
- plugins/cloglog/skills/launch/SKILL.md
- tests/test_auto_merge_gate.py
