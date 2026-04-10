# Post-Mortem: MCP Agent Registration Auth Failure

**Date:** 2026-04-10
**Duration:** ~6 sessions of debugging across one conversation
**Impact:** All MCP agent registration broken; no agents could register or heartbeat
**Resolution:** Commit f1b8bb8

## Summary

The MCP server's `register_agent` tool returned `401 Unauthorized` on every call, preventing agents from registering with the cloglog backend. Three independent bugs in the auth chain compounded to make the failure opaque: the first bug was masked by the second, and fixing both revealed the third.

## Timeline

### How the auth system was built (Apr 3-9)

| Date | Commit | What happened |
|------|--------|---------------|
| Apr 3 | `d492ea4` | MCP server created. Client uses single `apiKey` for registration. Works. |
| Apr 3 | `b0ed7fe` | `GET /gateway/me` added, protected by `CurrentProject` (project API key auth). |
| Apr 4 | `6b103a9` | Agent router wired into gateway. Registration endpoint uses `CurrentProject`. |
| Apr 4 | `2ced148` | `.mcp.json` created with `CLOGLOG_API_KEY` set to the project key. |
| Apr 7 | `f661e8e` | Three-tier access control middleware introduced (MCP service key, agent token, dashboard key). |
| **Apr 9** | **`cab456c`** | **Per-agent token auth (F-28). Refactors client to use dual keys. Bug #1 introduced.** |
| **Apr 9** | **`d42fa52`** | **Adds `GET /gateway/me` call after registration. Bug #2 introduced.** |
| **Apr 9** | **`5b37a74`** | **"Fix: don't rotate agent token on reconnect." Bug #3 introduced.** |

All three bugs were introduced on April 9 across three separate commits, merged via PRs #88-#90.

### The debugging session (Apr 10)

| Step | What we tried | What happened |
|------|--------------|---------------|
| 1 | Called `register_agent` | `401 Missing API key` |
| 2 | Analyzed auth system, found `CLOGLOG_API_KEY` not set | Rotated project key, set it in `.mcp.json` |
| 3 | Restarted session | `401 Missing API key` (MCP server still using old code) |
| 4 | Found client.ts sends `serviceKey` instead of `apiKey` for registration | Fixed Bug #1 in client.ts |
| 5 | Rebuilt, restarted | `401 Invalid API key` (progress! different error) |
| 6 | Verified key hash matches DB | Match confirmed |
| 7 | Tested registration via direct Python/Node.js calls | Both succeed |
| 8 | Multiple session restarts, cache clears | Same 401 from MCP tool |
| 9 | Added stderr logging to MCP server, redirected to file | **Breakthrough:** log shows register POST succeeds, but `GET /gateway/me` fails |
| 10 | Found `server.ts:83` calls `/gateway/me` with service key after register | Fixed Bug #2: return `project_id` in register response |
| 11 | Restarted, registration works | `agent_token: null` on reconnect, heartbeat 401 |
| 12 | Found `services.py` doesn't rotate token on reconnect | Fixed Bug #3: always rotate |
| 13 | Restarted, everything works | Registration + heartbeat confirmed |

## The Three Bugs

### Bug #1: Wrong credential for registration (client.ts)

**Introduced:** `cab456c` (Apr 9) — "feat: implement per-agent token authentication"
**Root cause:** When refactoring the MCP client to support three credential types, the registration route was assigned to use `this.serviceKey` + `X-MCP-Request: true` instead of `this.apiKey`.

```typescript
// BROKEN (cab456c)
if (isRegisterRoute || isUnregisterByPath) {
  headers['Authorization'] = `Bearer ${this.serviceKey}`  // wrong key
  headers['X-MCP-Request'] = 'true'                       // wrong header
}

// FIXED (f1b8bb8)
if (isRegisterRoute || isUnregisterByPath) {
  headers['Authorization'] = `Bearer ${this.apiKey}`       // project API key
}
```

The backend's `POST /api/v1/agents/register` uses `CurrentProject`, which hashes the bearer token and looks it up in the `projects.api_key_hash` column. Sending the MCP service key (`cloglog-mcp-dev`) instead of the project API key naturally fails.

**Why not caught:** The `apiKey` field was populated in the client config but never actually used anywhere after this refactor. No test verified which key was sent for registration — the client test only checked that `request()` was called with the right path.

### Bug #2: Post-registration call with wrong auth (server.ts)

**Introduced:** `d42fa52` (Apr 9) — "feat: add report_artifact MCP tool"
**Root cause:** After registration, `server.ts` needed the `project_id` to enable board operations. It fetched this by calling `GET /api/v1/gateway/me`, which requires `CurrentProject` auth. But the MCP client sent this as a board route (service key + `X-MCP-Request`), which the middleware passes through — then `CurrentProject` rejects the service key.

```typescript
// BROKEN (d42fa52): second call fails, error returned to caller
const result = await handlers.register_agent({ worktree_path })
const project = await handlers.get_project({})  // 401!
currentProjectId = project.id as string

// FIXED (f1b8bb8): project_id returned directly from registration
const result = await handlers.register_agent({ worktree_path })
currentProjectId = result.project_id as string   // no extra call needed
```

**Why this was the hardest bug to find:** The error message `401 Invalid API key` appeared to come from registration, but registration had already succeeded in the database. The `get_project()` call threw, and the MCP SDK propagated that error as the tool result. Nothing in the error indicated which HTTP call actually failed.

**Breakthrough:** Adding `console.error` before every `fetch()` and redirecting MCP server stderr to a file revealed the sequence: `POST /register` (success, no error logged) followed by `GET /gateway/me` (401 logged).

### Bug #3: Agent token not returned on reconnect (services.py)

**Introduced:** `5b37a74` (Apr 9) — "fix: don't rotate agent token on reconnect"
**Root cause:** The "fix" assumed that on reconnect, the caller already had a valid token from a previous registration. This is true if the same process reconnects. But MCP servers are ephemeral — each Claude Code session spawns a fresh Node.js process with no in-memory state.

```python
# BROKEN (5b37a74): reconnect returns None, new process has no token
if is_new or not worktree.agent_token_hash:
    agent_token = uuid4().hex
    # ... store hash
else:
    agent_token = None  # "caller already has it"

# FIXED (f1b8bb8): always rotate, new process always gets a token
agent_token = uuid4().hex
token_hash = hashlib.sha256(agent_token.encode()).hexdigest()
await self._repo.set_agent_token_hash(worktree.id, token_hash)
```

**Why not caught:** The original rotation behavior was correct. The "don't rotate" commit was a well-intentioned fix for a scenario that doesn't apply to MCP servers. The commit message and PR description frame it as preventing invalidation of "other processes" — but no other process shares the token. Each session is independent.

## Contributing Factors

### 1. No integration test for the full registration flow

Unit tests mocked the HTTP client, so they verified the tool called the right handler method — not that the right HTTP headers were sent. An integration test that started a real backend and called `register_agent` through the MCP server would have caught Bug #1 immediately.

### 2. Error masking across chained calls

Bug #2 was invisible because the MCP tool handler made two HTTP calls in sequence (`register` then `get_project`) and any exception from either appeared as the tool result. The successful registration was hidden by the subsequent failure.

### 3. Incorrect mental model of MCP server lifecycle

Bug #3 stems from treating the MCP server as a long-lived process that might reconnect while still holding a token. In reality, each Claude Code session spawns a fresh process. The token is only valid for the lifetime of that process — it must be returned on every registration.

### 4. MCP server stderr not visible

Claude Code captures MCP server stdout for JSON-RPC communication but discards stderr. Debug logging in the MCP server was invisible until we added a bash wrapper to redirect stderr to a file. This made it extremely difficult to observe what HTTP requests the MCP server was actually making.

### 5. Dead code went unnoticed

After the refactor in `cab456c`, `this.apiKey` was loaded from `CLOGLOG_API_KEY` and stored in the client but never used in any request path. This dead code was a clear signal that something was wrong, but no linter or test caught it.

## What Was Tried Before the Fix

1. **Rotated the project API key** via a new `scripts/rotate-project-key.py` — necessary since the original key was lost (only hash stored in DB), but didn't fix the auth chain.
2. **Multiple session restarts** — Claude Code MCP servers only pick up code changes on restart, leading to ~4 restart cycles where we thought we'd fixed the issue.
3. **Direct API testing** (Python `urllib`, Node.js) — proved the backend accepted the key, narrowing the problem to MCP client behavior.
4. **Process /proc inspection** — verified the running MCP server had correct env vars and loaded the correct dist files.
5. **Stderr redirect to file** — the breakthrough. Revealed the hidden second HTTP call that was actually failing.

## Fixes Applied (commit f1b8bb8)

| File | Change |
|------|--------|
| `mcp-server/src/client.ts` | Registration sends `apiKey` instead of `serviceKey`, no `X-MCP-Request` |
| `mcp-server/src/server.ts` | Reads `project_id` from register response, removes `GET /gateway/me` call |
| `mcp-server/src/index.ts` | Defaults `MCP_SERVICE_KEY` to `cloglog-mcp-dev` (was empty string) |
| `src/agent/services.py` | Always rotates agent token on registration |
| `src/agent/schemas.py` | Adds `project_id` to `RegisterResponse` |
| `.mcp.json` | Updated with rotated project API key |
| `scripts/rotate-project-key.py` | New utility for key recovery |
| `mcp-server/tests/*` | Updated to match new behavior |

## Action Items

- [ ] Add integration test: MCP server → real backend registration flow
- [ ] Add test that verifies `this.apiKey` is used for registration (not `serviceKey`)
- [ ] Add test that verifies heartbeat works after reconnect (token rotation)
- [ ] Consider making MCP server stderr visible in Claude Code (or log to a file by default)
- [ ] Add a startup self-check: MCP server could verify its own registration works on boot
- [ ] Document the three-tier auth system with a diagram in `docs/`
