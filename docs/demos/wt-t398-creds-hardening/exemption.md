---
verdict: no_demo
diff_hash: a1c4b92a55ad1d37695ff44de653eb914dea6c8f68aab7e1b070046473fae4b9
classifier: demo-classifier
generated_at: 2026-05-04T09:15:00Z
---

## Why no demo

No MCP tool name, description, or Zod input/output schema changed. The `register_agent` tool definition is identical; Guard 2 adds an internal validation path that returns `isError: true` on project_id mismatch — this is a security hardening guard, not a schema change. Guard 3 (`loadApiKey` strict fallback) only fires at MCP server startup when credentials are misconfigured, not during normal operation. The `resolve-api-key.sh` change is an internal hook guard. Init SKILL.md changes are documentation. No HTTP route decorators were added or modified, no React UI components were touched, and no CLI output surface changed.

The verdict would flip to `needs_demo` if any `server.tool()` registration (name, description, or `z.object` schema) had changed.

## Changed files

- mcp-server/src/credentials.ts
- mcp-server/src/index.ts
- mcp-server/src/server.ts
- mcp-server/tests/credentials.test.ts
- mcp-server/tests/server.test.ts
- plugins/cloglog/hooks/lib/resolve-api-key.sh
- plugins/cloglog/skills/init/SKILL.md
- tests/plugins/test_init_bootstrap_skill.py
- tests/plugins/test_init_mints_per_project_credentials.py
- tests/test_mcp_register_agent_verifies_project_id.py
