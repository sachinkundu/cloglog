---
verdict: no_demo
diff_hash: 5c9a2e48b5b2e8b349351e69fa8724f3a3a2a2ccfb520a64760cd2f00df91124
classifier: demo-classifier
generated_at: 2026-05-03T00:00:00Z
---

## Why no demo

All four files are plugin/skill internals: `auto_merge_gate.py` adds a
`DIRTY` `mergeStateStatus` check to a pure-Python helper,
`github-bot/SKILL.md` and `AGENT_PROMPT.md` document the new `pr_dirty`
branch, and `tests/test_auto_merge_gate.py` pins the truth table. No
HTTP routes, no React components, no MCP tool schema, no CLI stdout a
user reads, no DB migration. The strongest `needs_demo` candidate was
the new `pr_dirty` exit code from the gate CLI, but `auto_merge_gate.py`
is invoked by the agent skill (machine-to-machine) and not a user-read
CLI surface.

Counterfactual: if the diff had added or changed a `@router` decorator
under `src/**` (e.g., a new conflict-status endpoint in `src/gateway/`)
or modified a `server.tool` registration in `mcp-server/src/server.ts`,
the verdict would have flipped to `needs_demo`.

## Changed files

- plugins/cloglog/scripts/auto_merge_gate.py
- plugins/cloglog/skills/github-bot/SKILL.md
- plugins/cloglog/templates/AGENT_PROMPT.md
- tests/test_auto_merge_gate.py
