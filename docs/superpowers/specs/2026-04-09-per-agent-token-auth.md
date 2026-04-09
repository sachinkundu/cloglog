# Design Spec: Per-Agent Token Authentication (F-28)

**Date:** 2026-04-09
**Status:** Draft
**Context:** Gateway bounded context

---

## 1. Current Auth Analysis

### How auth works today

The system has three credential paths, enforced by `ApiAccessControlMiddleware` in `src/gateway/app.py:38-104`:

| Credential | Header(s) | Allowed Routes | Validated Against |
|---|---|---|---|
| **Agent API key** | `Authorization: Bearer <key>` | `/api/v1/agents/*` only | `BoardService.verify_api_key()` — SHA-256 hash lookup in `projects.api_key_hash` |
| **MCP server** | `Authorization: Bearer <key>` + `X-MCP-Request: true` | All routes | Middleware passes through if both headers present; `CurrentProject` validates key downstream |
| **Dashboard** | `X-Dashboard-Key` header or `dashboard_key` query param | Non-agent routes | `hmac.compare_digest` against `settings.dashboard_secret` |

Key flows:
- **API key generation:** `BoardService.create_project()` generates `secrets.token_hex(32)` (64 hex chars), stores `SHA-256(key)` in `projects.api_key_hash`. The plaintext is returned once and must be stored by the caller.
- **API key validation:** `CurrentProject` dependency (`src/gateway/auth.py:16-47`) extracts Bearer token, calls `verify_api_key()`, sets `request.state.project_id`.
- **MCP server auth:** The MCP server (`mcp-server/src/client.ts:32-38`) sends every request with both `Authorization: Bearer <CLOGLOG_API_KEY>` and `X-MCP-Request: true`. The key is the *same project API key* that agents use, read from `CLOGLOG_API_KEY` env var.
- **Agent routes:** Most agent routes take `worktree_id` as a path parameter but **never validate that the Bearer token's project owns that worktree**. The `CurrentProject` dependency is only used on `register` and `unregister-by-path`.

### Security gaps

1. **Shared credential — no agent isolation.** All agents in a project share one API key. Agent A can call `POST /agents/{agent_B_id}/heartbeat`, `POST /agents/{agent_B_id}/start-task`, `POST /agents/{agent_B_id}/request-shutdown`, etc. There is no validation that the caller owns the worktree_id in the URL.

2. **No worktree-to-token binding on most routes.** Only `register` and `unregister-by-path` use `CurrentProject`. Routes like `heartbeat`, `start-task`, `complete-task`, `update-task-status`, `assign-task`, `add-task-note`, `request-shutdown`, `send-agent-message` accept any Bearer token that passes middleware — they don't verify project ownership of the worktree.

3. **MCP server bypass is trivially easy.** The middleware distinguishes "MCP server" from "agent" solely by the presence of `X-MCP-Request: true` header. Any agent can add this header to gain access to board and document routes. The middleware does not validate MCP identity — it's defense-in-depth, not a security boundary.

4. **Dashboard secret is hardcoded.** `settings.dashboard_secret` defaults to `"cloglog-dashboard-dev"` and is loaded from `.env`. On a shared machine, any process can read this.

5. **Single project key = single point of compromise.** If the project API key leaks, all agent operations are compromised. There's no way to revoke one agent's access without rotating the key for all agents.

---

## 2. Token Generation and Storage

### Design: `agent_token` column on Worktree model

Add a token column to the existing `Worktree` model rather than a separate table. Rationale: a token is intrinsic to a worktree's identity — it lives and dies with the worktree row. A separate table adds a join with no benefit.

```python
# src/agent/models.py — Worktree model additions
class Worktree(Base):
    # ... existing columns ...
    agent_token_hash: Mapped[str] = mapped_column(String(255), default="")
```

### Token format: UUID4

Use `uuid.uuid4().hex` (32 hex chars). Rationale:
- **Not JWT.** JWTs are self-contained and can't be revoked without a blocklist. We need server-side revocation (deleting the worktree revokes the token).
- **Not HMAC-signed.** Unnecessary complexity — we're doing a DB lookup anyway for heartbeat, task status, etc.
- **UUID4 has 122 bits of entropy.** Sufficient for this use case (not internet-facing, short-lived tokens).
- **Stored as SHA-256 hash** — same pattern as project API keys. If the DB is compromised, tokens can't be recovered.

### Token lifecycle

1. **Generated at registration.** `AgentService.register()` creates the token, hashes it, stores the hash on the `Worktree` row, and returns the plaintext token in the `RegisterResponse`.
2. **Used for all subsequent requests.** The agent uses `Authorization: Bearer <agent_token>` instead of the project API key.
3. **Revoked on unregister.** Deleting the worktree row deletes the hash. The token is immediately invalid.
4. **Rotated on re-registration.** If a worktree path re-registers (session reconnect), a new token is generated. The old token is invalidated. This prevents stale sessions from operating.

### Registration flow change

Current:
```
Agent → POST /agents/register (Authorization: Bearer <project_api_key>)
      ← { worktree_id, session_id, current_task, resumed }
```

Proposed:
```
Agent → POST /agents/register (Authorization: Bearer <project_api_key>)
      ← { worktree_id, session_id, current_task, resumed, agent_token }

# All subsequent requests use agent_token, not project_api_key
Agent → POST /agents/{wt_id}/heartbeat (Authorization: Bearer <agent_token>)
```

The `register` endpoint remains the only agent endpoint that accepts the project API key. All other agent endpoints require the agent token.

---

## 3. Token Validation Middleware

### Design: Extend `CurrentProject` or add new dependency

Add a new FastAPI dependency `CurrentAgent` that validates agent tokens:

```python
# src/gateway/auth.py additions

async def get_current_agent(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Worktree:
    """Validate agent token and return the authenticated Worktree.
    
    Also verifies that the token matches the worktree_id in the URL path.
    """
    token = _extract_bearer_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail="Missing agent token")
    
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    repo = AgentRepository(session)
    worktree = await repo.get_worktree_by_token_hash(token_hash)
    if worktree is None:
        raise HTTPException(status_code=401, detail="Invalid agent token")
    
    # Verify token matches the worktree_id in the URL
    worktree_id_param = request.path_params.get("worktree_id")
    if worktree_id_param and UUID(worktree_id_param) != worktree.id:
        raise HTTPException(
            status_code=403,
            detail="Agent token does not match worktree_id in URL"
        )
    
    request.state.worktree = worktree
    request.state.project_id = worktree.project_id
    return worktree

CurrentAgent = Annotated[Worktree, Depends(get_current_agent)]
```

### Route changes

| Route | Current Auth | New Auth |
|---|---|---|
| `POST /agents/register` | `CurrentProject` (project API key) | `CurrentProject` (unchanged — bootstrapping) |
| `POST /agents/{wt_id}/heartbeat` | None (any Bearer passes middleware) | `CurrentAgent` |
| `GET /agents/{wt_id}/tasks` | None | `CurrentAgent` |
| `PATCH /agents/{wt_id}/assign-task` | None | `CurrentAgent` or `CurrentMcpService` |
| `POST /agents/{wt_id}/start-task` | None | `CurrentAgent` |
| `POST /agents/{wt_id}/complete-task` | None | `CurrentAgent` |
| `PATCH /agents/{wt_id}/task-status` | None | `CurrentAgent` |
| `POST /agents/{wt_id}/task-note` | None | `CurrentAgent` |
| `POST /agents/{wt_id}/request-shutdown` | None | `CurrentMcpService` (only MCP/master can shutdown others) |
| `POST /agents/unregister-by-path` | `CurrentProject` | `CurrentProject` or `CurrentMcpService` |
| `POST /agents/{wt_id}/unregister` | None | `CurrentAgent` (self-unregister) |
| `POST /agents/{wt_id}/message` | None | `CurrentMcpService` (only MCP can send messages to agents) |
| `GET /projects/{pid}/worktrees` | None | `CurrentMcpService` or Dashboard |

### Performance: DB lookup per request

Every agent request already hits the DB (heartbeat updates, task queries, etc.). Adding one indexed lookup on `agent_token_hash` (VARCHAR(255) with unique index) adds negligible overhead — one hash computation + one index scan.

No caching needed. Agent tokens are short-lived (hours, not days), and the lookup is on a small table (tens of rows, not millions). Premature caching would add invalidation complexity for no measurable gain.

### Middleware changes

The `ApiAccessControlMiddleware` needs a fourth path:

```python
# Path 1: MCP service key + X-MCP-Request — allowed everywhere
if auth and mcp and self._is_valid_mcp_key(auth_token):
    request.state.auth_type = "mcp"
    return await call_next(request)

# Path 2: Agent token — restricted to agent routes (validated downstream by CurrentAgent)
if auth and not mcp and is_agent_route:
    request.state.auth_type = "agent"
    return await call_next(request)

# Path 3: Project API key — only for /agents/register and /agents/unregister-by-path
if auth and not mcp and is_registration_route:
    request.state.auth_type = "project"
    return await call_next(request)

# Path 4: Dashboard key — non-agent routes
if dashboard_key:
    # ... existing logic
```

The middleware doesn't validate tokens — it classifies the request type. The `CurrentAgent` / `CurrentProject` / `CurrentMcpService` dependencies do the actual validation. This separation keeps the middleware fast (no DB calls) and the route handlers authoritative.

---

## 4. MCP Service Key Design

### Problem

Today the MCP server uses the same project API key as agents, distinguished only by `X-MCP-Request: true`. This is a header-based honor system, not a security boundary.

### Design: Separate MCP service key

Introduce a dedicated MCP service key, distinct from both the project API key and agent tokens.

**Configuration:**
```python
# src/shared/config.py
class Settings(BaseSettings):
    # ... existing ...
    mcp_service_key: str = ""  # Set via MCP_SERVICE_KEY env var
```

**Where it lives:** Environment variable `MCP_SERVICE_KEY`, configured in the MCP server's runtime environment (Claude Code's `settings.json` under `mcpServers.cloglog.env`).

**Generation:** Created alongside the project API key during `create_project`, or set manually via CLI/env. Stored as SHA-256 hash in a new `mcp_service_key_hash` column on `Project`, or (simpler) as a static secret in settings — since there's only one MCP server instance per project.

**Recommendation: Static secret in settings** (like `dashboard_secret`). Rationale:
- There's exactly one MCP server per agent session on this machine.
- It doesn't need per-project scoping — it's a local infrastructure credential.
- Avoids DB lookup overhead on every MCP request (which is every MCP tool call).

```python
# src/shared/config.py
class Settings(BaseSettings):
    mcp_service_key: str = "cloglog-mcp-dev"  # Override in production
```

**Validation:** New dependency:

```python
async def get_mcp_service(request: Request) -> None:
    """Validate MCP service key. No DB lookup needed."""
    auth = request.headers.get("Authorization", "")
    mcp_header = request.headers.get("X-MCP-Request")
    
    if not mcp_header:
        raise HTTPException(status_code=403, detail="Not an MCP request")
    
    token = auth.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(token, settings.mcp_service_key):
        raise HTTPException(status_code=401, detail="Invalid MCP service key")

CurrentMcpService = Annotated[None, Depends(get_mcp_service)]
```

### MCP server changes

```typescript
// mcp-server/src/index.ts
const CLOGLOG_URL = process.env.CLOGLOG_URL ?? 'http://localhost:8000'
const MCP_SERVICE_KEY = process.env.MCP_SERVICE_KEY ?? ''

// mcp-server/src/client.ts
headers: {
  'Authorization': `Bearer ${this.serviceKey}`,
  'X-MCP-Request': 'true',
}
```

The MCP server no longer needs `CLOGLOG_API_KEY`. It uses `MCP_SERVICE_KEY` instead.

### How middleware distinguishes credential types

| Header(s) | Credential Type |
|---|---|
| `Authorization` + `X-MCP-Request` | MCP service key |
| `Authorization` only, on `/agents/register` or `/agents/unregister-by-path` | Project API key |
| `Authorization` only, on other `/agents/*` routes | Agent token |
| `X-Dashboard-Key` | Dashboard key |

---

## 5. Migration Path

### Phase 1: Add infrastructure (non-breaking)

1. Add `agent_token_hash` column to `Worktree` model (Alembic migration, nullable, defaults to `""`)
2. Add `mcp_service_key` to Settings
3. Add `CurrentAgent` and `CurrentMcpService` dependencies (unused yet)
4. Modify `register()` to generate and return `agent_token` in response
5. MCP server updated to use `MCP_SERVICE_KEY`

At this point, both old (project API key) and new (agent token) work on agent routes. The middleware still passes any Bearer token through.

### Phase 2: Enforce agent tokens (soft — log warnings)

1. Routes gain `CurrentAgent` dependency but with a fallback: if agent token validation fails, fall back to project API key validation and log a deprecation warning.
2. This lets running agents continue working while new agents pick up the token from registration.

### Phase 3: Hard enforcement

1. Remove project API key fallback on agent routes.
2. Only `register` and `unregister-by-path` accept project API keys.
3. All other agent routes require agent tokens.

### Timeline

Phase 1 and 2 can ship together. Phase 3 ships after verifying all agents use tokens (check logs for deprecation warnings). In practice, agents are short-lived (hours), so a 24-hour window between phases is sufficient.

### MCP server migration

The MCP server needs to:
1. Start sending `MCP_SERVICE_KEY` instead of `CLOGLOG_API_KEY`
2. Capture the `agent_token` from `register_agent` response
3. For agent-scoped requests (heartbeat, task status), use the agent token
4. For board/document requests, continue using MCP service key

This is a code change in `mcp-server/src/client.ts` and `mcp-server/src/server.ts`. The MCP server already stores `currentWorktreeId` — it would additionally store `currentAgentToken` after registration.

---

## 6. The Honest Gap: Single-Machine Threat Model

### What this design prevents

- **Agent impersonation via API.** Agent A cannot call agent B's endpoints — the token won't match.
- **MCP bypass via header spoofing.** Adding `X-MCP-Request: true` no longer grants access — you need the MCP service key, which is a different credential.
- **Blast radius of token compromise.** A leaked agent token affects one worktree, not all agents in the project.
- **Stale session operations.** Re-registration rotates the token, invalidating any lingering old session.

### What this design does NOT prevent

**All agents run on the same machine as the same OS user.** This means:

1. **Filesystem access to credentials.** An agent can read:
   - Its own `.env` file (contains `DATABASE_URL`, ports — not API keys today, won't contain tokens either)
   - The MCP server's environment via `/proc/<pid>/environ` (if they know the PID) — this would reveal `MCP_SERVICE_KEY`
   - `~/.claude/projects/*/settings.json` or wherever Claude Code stores MCP env vars — would reveal `MCP_SERVICE_KEY`
   - Other worktrees' `.env` files and source code
   - The database directly via `psql` — credentials are in the shared `docker-compose.yml`

2. **Direct database access.** Any agent can connect to PostgreSQL and read/write any table. Tokens stored as hashes mitigate this slightly (you can't extract a valid token from the hash), but an agent could INSERT a known hash, or UPDATE `agent_token_hash` on another worktree.

3. **Process inspection.** `ps aux`, `/proc/*/environ`, `lsof` — any agent can see other agents' processes and environment variables.

4. **Network sniffing.** All traffic is `localhost` HTTP (not HTTPS). Any process can sniff it. Tokens travel in plaintext over the loopback interface.

### Honest assessment

This design moves from "any agent can impersonate any other agent trivially via the API" to "an agent would need to actively exploit filesystem/process/DB access to impersonate another agent." It raises the bar from "use the shared API key" to "read another process's memory or query the DB directly."

On a single-machine, single-user setup, this is **defense-in-depth against accidental misuse, not a security boundary against a malicious agent.** A truly malicious agent (one that has been prompt-injected or is running adversarial code) can bypass this by:
- Reading the MCP service key from the filesystem
- Connecting to the database directly
- Sniffing localhost traffic

**This is acceptable** for the current threat model (autonomous AI agents on a dev machine). The real threat is *accidental* cross-agent interference, not adversarial agents. The design makes it impossible to accidentally call another agent's endpoints, which is the primary goal.

### Future hardening (out of scope for F-28)

If the system moves to multi-machine (agent-vm sandboxes with network isolation):
- Each agent gets its own network namespace — no sniffing, no direct DB access
- MCP service key is injected by the orchestrator, not readable from filesystem
- HTTPS between agents and backend
- At that point, this token design becomes a real security boundary

---

## 7. Impact on Existing Code

### Backend changes

| File | Change |
|---|---|
| `src/agent/models.py` | Add `agent_token_hash` column to `Worktree` |
| `src/agent/repository.py` | Add `get_worktree_by_token_hash()` method |
| `src/agent/services.py` | `register()` generates token, returns it; `unregister()` no change (row deletion handles it) |
| `src/agent/schemas.py` | `RegisterResponse` adds `agent_token` field |
| `src/agent/routes.py` | Most routes add `CurrentAgent` dependency; `request-shutdown` and `message` get `CurrentMcpService` |
| `src/gateway/auth.py` | Add `CurrentAgent`, `CurrentMcpService` dependencies |
| `src/gateway/app.py` | Update middleware to classify credential types; validate MCP service key |
| `src/shared/config.py` | Add `mcp_service_key` setting |
| `src/alembic/versions/` | Migration to add `agent_token_hash` column |

### MCP server changes

| File | Change |
|---|---|
| `mcp-server/src/index.ts` | Read `MCP_SERVICE_KEY` instead of `CLOGLOG_API_KEY` |
| `mcp-server/src/client.ts` | Add `serviceKey` for MCP requests; add `agentToken` for agent-scoped requests; `register` captures token |
| `mcp-server/src/server.ts` | `register_agent` handler stores returned `agent_token` for use in subsequent agent requests |

### Script changes

| File | Change |
|---|---|
| `scripts/create-worktree.sh` | No change — API key is not in `.env` |
| Claude Code `settings.json` | MCP server env needs `MCP_SERVICE_KEY` instead of (or in addition to) `CLOGLOG_API_KEY` during migration |

### Test changes

- New unit tests for `CurrentAgent` dependency (valid token, invalid token, wrong worktree_id)
- New unit tests for `CurrentMcpService` dependency
- New integration tests for agent route auth (heartbeat with wrong token rejected, etc.)
- Update existing agent route tests to use agent tokens from registration
- New tests for token rotation on re-registration

---

## 8. Summary of Credential Types

| Credential | Generated | Stored | Used For | Validated By |
|---|---|---|---|---|
| **Project API key** | `create_project()` — `secrets.token_hex(32)` | SHA-256 hash in `projects.api_key_hash` | Agent registration only | `CurrentProject` |
| **Agent token** | `register()` — `uuid4().hex` | SHA-256 hash in `worktrees.agent_token_hash` | All agent-scoped routes | `CurrentAgent` |
| **MCP service key** | Static config / env var | Plaintext in `settings.mcp_service_key` | Board, document, cross-agent routes | `CurrentMcpService` |
| **Dashboard secret** | Static config / env var | Plaintext in `settings.dashboard_secret` | Dashboard API access | `hmac.compare_digest` in middleware |

---

## 9. Open Questions

1. **Should the MCP service key be per-project (stored in DB) or global (in settings)?** This spec recommends global/settings for simplicity. If multi-project-per-machine becomes common, revisit.

2. **Should agent tokens have TTL?** Currently they're valid until worktree unregistration. Adding a TTL (e.g., 24 hours) with rotation on heartbeat would limit the window of a leaked token, but adds complexity. Recommendation: skip for now — worktree lifecycle already handles this.

3. **Should `assign-task` accept agent tokens?** Currently the master agent calls `assign-task` on behalf of other worktrees. With per-agent tokens, the master agent would need the MCP service key to assign tasks to other worktrees. This is the correct behavior — task assignment is a coordination operation, not a self-service operation.
