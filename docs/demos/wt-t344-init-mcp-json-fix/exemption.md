---
verdict: no_demo
diff_hash: 08842a344eae1bca147494ee1f8993f049ab16adcb8979cff9c38689f0538994
classifier: demo-classifier
generated_at: 2026-04-29T00:00:00Z
---

## Why no demo

Diff touches only README.md, plugins/cloglog/skills/init/SKILL.md, and
tests/plugins/test_init_on_fresh_repo.py — a SKILL.md fix that retargets
the Step 3 merge to write mcpServers into .mcp.json instead of
.claude/settings.json (T-344), with corresponding test updates and doc
note. No HTTP route decorators, no React components, no MCP tool
registrations in mcp-server/src/server.ts, no CLI output surface, no DB
migrations.

Strongest needs_demo candidate considered: the change alters what files
a fresh `init` produces on disk — but that is internal plumbing of the
bootstrap flow, not a user-observable surface (the resulting MCP tool
surface and routes are unchanged). If the diff had added or modified a
`server.tool(...)` registration in mcp-server/src/server.ts, or added a
new `@router.*` decorator, I would have flipped to needs_demo with
mcp-tool-exec or backend-curl.

## Changed files

- README.md
- plugins/cloglog/skills/init/SKILL.md
- tests/plugins/test_init_on_fresh_repo.py
