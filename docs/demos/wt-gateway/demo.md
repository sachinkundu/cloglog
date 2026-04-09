# Demo: Per-Agent Token Auth Design Spec (F-28 / T-141)

This is a design spec PR — no runnable code to demo.

## What was produced

The spec at `docs/superpowers/specs/2026-04-09-per-agent-token-auth.md` covers:

1. **Current auth analysis** — mapped all three credential paths, identified five security gaps
2. **Token design** — UUID4 agent tokens, SHA-256 hashed, stored on Worktree model
3. **Validation middleware** — `CurrentAgent` dependency with worktree_id binding
4. **MCP service key** — separate credential type, static config
5. **Migration path** — three-phase rollout with backwards compatibility
6. **Threat model** — honest assessment of single-machine limitations
7. **Impact analysis** — every file that needs changes across backend, MCP server, and scripts

## Source files analyzed

- `src/gateway/app.py` (ApiAccessControlMiddleware)
- `src/gateway/auth.py` (CurrentProject dependency)
- `src/agent/routes.py` (all agent endpoints)
- `src/agent/models.py` (Worktree, Session models)
- `src/agent/services.py` (registration, heartbeat, task lifecycle)
- `src/shared/config.py` (settings)
- `mcp-server/src/client.ts` (HTTP client auth headers)
- `mcp-server/src/server.ts` (tool handlers, MCP request flow)
- `mcp-server/src/index.ts` (env var configuration)
- `scripts/create-worktree.sh` (worktree setup)
- `scripts/worktree-infra.sh` (infrastructure isolation)
