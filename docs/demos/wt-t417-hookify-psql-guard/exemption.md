---
verdict: no_demo
diff_hash: aec6f2992b8c092ba575c286f4e1aed678d6d6866af32395cbde717f57307cff
classifier: demo-classifier
generated_at: 2026-05-14T10:40:40Z
---

## Why no demo

Diff adds a Claude Code PreToolUse hook (plugins/cloglog/hooks/block-direct-db.sh), its settings.json registration, a pin test, and a CLAUDE.md doc section. No HTTP routes, React components, MCP tool schemas, CLI output, or DB migrations change — this is internal agent-tooling plumbing invisible at any user-facing boundary. The strongest counter-signal was the settings.json change, but it only wires a developer-environment guard, not a product surface. If the change had added/altered an mcp__cloglog__* tool in mcp-server/src/server.ts or a @router.* endpoint, the verdict would flip to needs_demo.

## Changed files

- CLAUDE.md
- Makefile
- docs/invariants.md
- plugins/cloglog/hooks/block-direct-db.sh
- plugins/cloglog/settings.json
- tests/plugins/test_block_direct_db_hook.py
