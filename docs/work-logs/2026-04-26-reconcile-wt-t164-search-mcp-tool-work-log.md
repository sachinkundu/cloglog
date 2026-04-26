# Work log — wt-t164-search-mcp-tool

## Task

T-164 — Add `search` MCP tool wrapping the existing backend search endpoint
(`GET /api/v1/projects/{project_id}/search?q=...`).

## What shipped

PR: https://github.com/sachinkundu/cloglog/pull/221 (merged)

- `mcp-server/src/tools.ts` — `search` handler in `ToolHandlers` /
  `createToolHandlers`. Uses `URLSearchParams` to encode `q`, optional
  `limit`, and repeated `status_filter` keys (matches the FastAPI
  `list[str] | None` parser shape in `src/board/routes.py:495`).
- `mcp-server/src/server.ts` — registers the `search` tool with
  `requireProject()` gating (same pattern as `get_board`, `list_epics`),
  so agents only pass `query` and the project_id is resolved from the
  registered agent context.
- `mcp-server/src/__tests__/tools.test.ts` — three handler-layer pins:
  entity-number query (`T-42`), URL-encoded free text, and
  `limit + multi status_filter`.
- `mcp-server/tests/server.test.ts` — two server-registration pins:
  `Not registered` guard before `register_agent`; correct end-to-end
  URL after register.
- `docs/demos/wt-t164-search-mcp-tool/` — Showboat demo with five
  proofs (registration in source, handler URL parity with the CLI,
  vitest pin pass, backend route present, full vitest pass count).

Backend behaviour unchanged; this PR purely exposes the existing search
route over the MCP boundary. No contract changes; no new migrations.

## Test deltas

- mcp-server vitest: 83 → 88 passed (+5).
- backend pytest: 857 passed / 1 xfailed (unchanged).
- contract-check: compliant (unchanged).

## Review

Codex round 1/5 passed (`:pass:`); no review comments. Human merged.

## Lifecycle events

- agent_started → main inbox
- task → in_progress → review (with PR URL) → pr_merged → mark_pr_merged
- shutdown sequence (this file)
