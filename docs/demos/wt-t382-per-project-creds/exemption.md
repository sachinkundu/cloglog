---
verdict: no_demo
diff_hash: bdfb4f2544c416ea88074b568a812d835b87940edf7262cc0180068f943ac546
classifier: demo-classifier
generated_at: 2026-05-03T00:00:00Z
---

## Why no demo

Diff is internal credential-resolution plumbing: `mcp-server/src/credentials.ts` adds a per-project lookup layer (`~/.cloglog/credentials.d/<slug>`) before the legacy global file, with matching bash helpers (`_project_slug`, `_read_credentials_file`) in `plugins/cloglog/skills/launch/SKILL.md`'s `_api_key`. Remaining changes are docs (`docs/setup-credentials.md`, `plugins/cloglog/docs/setup-credentials.md`, `docs/invariants.md`), test additions (`mcp-server/tests/credentials.test.ts`, `tests/plugins/test_launch_skill_per_project_credentials.py`), and a `Makefile` invariants-list line. No `@router.*` decorators, no React components, no `server.tool(...)` registrations, no CLI stdout surface, no migrations — the MCP tool surface is unchanged; only how the MCP server discovers its own API key changes, which is invisible to stakeholders.

Counterfactual: if the diff had altered any `server.tool` registration in `mcp-server/src/server.ts` to expose project context, or added a `@router.get` for credential management, I would have flipped to needs_demo.

## Changed files

- Makefile
- docs/invariants.md
- docs/setup-credentials.md
- mcp-server/src/credentials.ts
- mcp-server/tests/credentials.test.ts
- plugins/cloglog/docs/setup-credentials.md
- plugins/cloglog/skills/launch/SKILL.md
- tests/plugins/test_launch_skill_per_project_credentials.py
