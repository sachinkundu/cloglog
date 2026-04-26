---
verdict: no_demo
diff_hash: 1cca0078b52191550e8344b4e1adce3c1d67996552c89400c47c1a33cf427ff7
classifier: demo-classifier
generated_at: 2026-04-26T10:01:17Z
---

## Why no demo

Diff is internal plumbing: a new pure-Python decision helper at
`plugins/cloglog/scripts/auto_merge_gate.py`, two pin tests
(`tests/test_auto_merge_gate.py`,
`tests/plugins/test_auto_merge_skill_handles_silent_holds.py`), and prose
updates to `docs/design/agent-lifecycle.md` plus the github-bot and launch
SKILL.md files. No HTTP route decorators, no React components, no MCP tool
definitions in `mcp-server/src/server.ts`, no CLI output a user reads, no DB
migration. Strongest `needs_demo` candidate considered: the
`auto_merge_gate.py` CLI prints a hold reason and exits 0/1 — but it's
invoked by the worktree agent skill, not by a human, so it fails the "CLI
output surface" test. Counterfactual: if the change had added a new
`@router.post` in `src/gateway/webhook.py` to surface label-change events,
or changed a server.tool schema in `mcp-server/src/server.ts`, the verdict
would have flipped to `needs_demo`.

## Changed files

- docs/demos/wt-t295-auto-merge/exemption.md
- docs/design/agent-lifecycle.md
- plugins/cloglog/scripts/auto_merge_gate.py
- plugins/cloglog/skills/github-bot/SKILL.md
- plugins/cloglog/skills/launch/SKILL.md
- tests/plugins/test_auto_merge_skill_handles_silent_holds.py
- tests/test_auto_merge_gate.py
