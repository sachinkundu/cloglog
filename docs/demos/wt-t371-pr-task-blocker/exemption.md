---
verdict: no_demo
diff_hash: 1b49eaba2fecca03df23fdf4b32d79e857b928cc95d69f4e5204b633fe1b83da
classifier: demo-classifier
generated_at: 2026-05-02T12:45:00Z
---

## Why no demo

Diff touches MCP server internals (state.json persistence in register/unregister
handlers), a PreToolUse hook script (`plugins/cloglog/hooks/require-task-for-pr.sh`),
close-wave/reconcile SKILL.md docs, and pin tests. No `server.tool(...)`
registration is added or changed — the tool surface (name, description, Zod
schema) is identical; only handler side-effects expanded. No HTTP routes, no
frontend, no CLI output, no DB migration. The strongest candidate for
needs_demo was the server.ts change, but it's an internal write to a state
file consumed by an out-of-process hook, invisible at the MCP boundary.
Counterfactual: if `server.tool(...)` had gained a new tool or a changed
input schema, or if the hook's user-facing block message qualified as a CLI
surface a stakeholder reads, I'd flip to needs_demo.

## Changed files

- mcp-server/src/client.ts
- mcp-server/src/server.ts
- mcp-server/src/state.ts
- mcp-server/tests/server.test.ts
- mcp-server/tests/state.test.ts
- plugins/cloglog/hooks/require-task-for-pr.sh
- plugins/cloglog/skills/close-wave/SKILL.md
- plugins/cloglog/skills/reconcile/SKILL.md
- tests/plugins/test_close_wave_skill_lifecycle_calls.py
- tests/plugins/test_require_task_for_pr_blocks.py
