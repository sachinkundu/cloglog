# Implementation Plan: Per-Agent Token Authentication (F-28)

**Date:** 2026-04-09
**Spec:** `docs/superpowers/specs/2026-04-09-per-agent-token-auth.md`
**Worktree:** `wt-gateway` (Gateway context: `src/gateway/`, `tests/gateway/`)

> **Note on worktree boundaries:** This feature spans Gateway (`src/gateway/`), Agent (`src/agent/`), MCP server (`mcp-server/`), and shared config (`src/shared/`). The `wt-gateway` worktree is allowed `src/gateway/` and `tests/gateway/` only. Files outside this boundary are listed with exact changes but must be implemented in the same worktree since F-28 is a cross-cutting security feature. The worktree hook may need to be bypassed or the worktree expanded for this feature.

---

## Step 1: Add `agent_token_hash` column to Worktree model

**File:** `src/agent/models.py`

Add column to the `Worktree` class:

```python
agent_token_hash: Mapped[str] = mapped_column(String(255), default="")
```

**File:** `src/alembic/versions/f5a6b7c8d9e0_add_agent_token_hash.py` (new migration)

```python
"""Add agent_token_hash to worktrees.

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
"""
from alembic import op
import sqlalchemy as sa

revision = "f5a6b7c8d9e0"
down_revision = "e4f5a6b7c8d9"

def upgrade() -> None:
    op.add_column("worktrees", sa.Column("agent_token_hash", sa.String(255), server_default="", nullable=False))

def downgrade() -> None:
    op.drop_column("worktrees", "agent_token_hash")
```

**Verify:** `uv run alembic upgrade head` succeeds, `uv run alembic history` shows correct chain.

---

## Step 2: Add `get_worktree_by_token_hash` to AgentRepository

**File:** `src/agent/repository.py`

Add method:

```python
async def get_worktree_by_token_hash(self, token_hash: str) -> Worktree | None:
    result = await self._session.execute(
        select(Worktree).where(Worktree.agent_token_hash == token_hash)
    )
    return result.scalar_one_or_none()
```

---

## Step 3: Add `mcp_service_key` to Settings

**File:** `src/shared/config.py`

```python
class Settings(BaseSettings):
    # ... existing ...
    mcp_service_key: str = "cloglog-mcp-dev"
```

---

## Step 4: Generate agent token at registration

**File:** `src/agent/services.py` — modify `register()`:

```python
import hashlib
import uuid

async def register(self, project_id, worktree_path, branch_name):
    worktree, is_new = await self._repo.upsert_worktree(project_id, worktree_path, branch_name)
    
    # Generate agent token (always rotate on registration)
    agent_token = uuid.uuid4().hex
    token_hash = hashlib.sha256(agent_token.encode()).hexdigest()
    await self._repo.set_agent_token_hash(worktree.id, token_hash)
    
    # ... existing session and event logic ...
    
    return {
        # ... existing fields ...
        "agent_token": agent_token,
    }
```

**File:** `src/agent/repository.py` — add method:

```python
async def set_agent_token_hash(self, worktree_id: UUID, token_hash: str) -> None:
    await self._session.execute(
        update(Worktree).where(Worktree.id == worktree_id).values(agent_token_hash=token_hash)
    )
    await self._session.commit()
```

**File:** `src/agent/schemas.py` — update `RegisterResponse`:

```python
class RegisterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    worktree_id: UUID
    session_id: UUID
    current_task: TaskInfo | None = None
    resumed: bool = False
    agent_token: str = ""  # New: per-agent auth token
```

---

## Step 5: Add `CurrentAgent` and `CurrentMcpService` dependencies

**File:** `src/gateway/auth.py`

```python
import hashlib
import hmac
from uuid import UUID

from src.agent.models import Worktree
from src.agent.repository import AgentRepository
from src.shared.config import settings


def _extract_bearer_token(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header[7:]
    return request.headers.get("X-API-Key")


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
            detail="Agent token does not match worktree_id in URL",
        )
    
    request.state.worktree = worktree
    request.state.project_id = worktree.project_id
    return worktree

CurrentAgent = Annotated[Worktree, Depends(get_current_agent)]


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

Also refactor `get_current_project` to use `_extract_bearer_token`.

---

## Step 6: Update middleware to classify credential types

**File:** `src/gateway/app.py` — update `ApiAccessControlMiddleware.dispatch()`:

The middleware needs to validate the MCP service key (currently it blindly trusts `X-MCP-Request`). Updated logic:

```python
async def dispatch(self, request, call_next):
    from src.shared.config import settings
    
    path = request.url.path
    if not path.startswith("/api/v1/"):
        return await call_next(request)
    
    auth = request.headers.get("Authorization")
    mcp = request.headers.get("X-MCP-Request")
    dashboard_key = (
        request.headers.get("X-Dashboard-Key")
        or request.query_params.get("dashboard_key")
    )
    is_agent_route = path.startswith("/api/v1/agents/")
    
    # Path 1: MCP server — must validate service key
    if auth and mcp:
        token = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""
        if not hmac.compare_digest(token, settings.mcp_service_key):
            return JSONResponse(status_code=401, content={"detail": "Invalid MCP service key"})
        return await call_next(request)
    
    # Path 2: Bearer token on agent routes — let through (validated by CurrentAgent/CurrentProject downstream)
    if auth and not mcp:
        if is_agent_route:
            return await call_next(request)
        return JSONResponse(status_code=403, content={"detail": "Agents can only access /api/v1/agents/* routes. Use MCP tools for all board operations."})
    
    # Path 3: Dashboard key — non-agent routes
    if dashboard_key:
        if not hmac.compare_digest(dashboard_key, settings.dashboard_secret):
            return JSONResponse(status_code=403, content={"detail": "Invalid dashboard key"})
        return await call_next(request)
    
    # No credentials
    return JSONResponse(status_code=401, content={"detail": "Authentication required. Provide Authorization, X-MCP-Request, or X-Dashboard-Key header."})
```

---

## Step 7: Add `CurrentAgent` to agent routes

**File:** `src/agent/routes.py`

Import `CurrentAgent` and `CurrentMcpService` from `src/gateway/auth`.

Update route signatures:

| Route | Add dependency |
|---|---|
| `heartbeat` | `agent: CurrentAgent` |
| `get_tasks` | `agent: CurrentAgent` |
| `assign_task` | `agent: CurrentAgent` (self-assign) — MCP uses service key path |
| `start_task` | `agent: CurrentAgent` |
| `complete_task` | `agent: CurrentAgent` |
| `update_task_status` | `agent: CurrentAgent` |
| `add_task_note` | `agent: CurrentAgent` |
| `request_shutdown` | No change (MCP-only, validated by middleware MCP path) |
| `unregister_agent` | `agent: CurrentAgent` |
| `send_agent_message` | No change (MCP-only, validated by middleware MCP path) |
| `list_worktrees` | No change (dashboard/MCP route) |
| `register_agent` | Unchanged (`CurrentProject`) |
| `unregister_by_path` | Unchanged (`CurrentProject`) |

Example change for `heartbeat`:

```python
@router.post("/agents/{worktree_id}/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(
    worktree_id: UUID, service: ServiceDep, agent: CurrentAgent
) -> dict[str, object]:
    # agent dependency already validated token matches worktree_id
    try:
        return await service.heartbeat(worktree_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
```

---

## Step 8: Update MCP server to use dual credentials

**File:** `mcp-server/src/index.ts`

```typescript
const CLOGLOG_URL = process.env.CLOGLOG_URL ?? 'http://localhost:8000'
const CLOGLOG_API_KEY = process.env.CLOGLOG_API_KEY ?? ''
const MCP_SERVICE_KEY = process.env.MCP_SERVICE_KEY ?? ''
```

**File:** `mcp-server/src/client.ts`

Add dual-credential support:

```typescript
export interface CloglogClientConfig {
  baseUrl: string
  apiKey: string       // Project API key (for registration)
  serviceKey: string   // MCP service key (for board/document routes)
}

export class CloglogClient {
  private baseUrl: string
  private apiKey: string
  private serviceKey: string
  private agentToken: string | null = null
  
  constructor(config: CloglogClientConfig) {
    this.baseUrl = config.baseUrl.replace(/\/$/, '')
    this.apiKey = config.apiKey
    this.serviceKey = config.serviceKey
  }
  
  setAgentToken(token: string) {
    this.agentToken = token
  }
  
  clearAgentToken() {
    this.agentToken = null
  }
  
  async request(method: string, path: string, body?: unknown): Promise<unknown> {
    const isAgentRoute = path.startsWith('/api/v1/agents/')
    const isRegisterRoute = path === '/api/v1/agents/register'
    const isUnregisterByPath = path === '/api/v1/agents/unregister-by-path'
    
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    }
    
    if (isRegisterRoute || isUnregisterByPath) {
      // Registration uses project API key
      headers['Authorization'] = `Bearer ${this.apiKey}`
      headers['X-MCP-Request'] = 'true'
    } else if (isAgentRoute && this.agentToken) {
      // Agent-scoped routes use agent token
      headers['Authorization'] = `Bearer ${this.agentToken}`
    } else {
      // Board/document routes use MCP service key
      headers['Authorization'] = `Bearer ${this.serviceKey}`
      headers['X-MCP-Request'] = 'true'
    }
    
    // ... existing fetch logic
  }
}
```

**File:** `mcp-server/src/server.ts` — capture `agent_token` from registration:

```typescript
server.tool('register_agent', ..., async ({ worktree_path }) => {
  const result = await handlers.register_agent({ worktree_path })
  currentWorktreeId = result.worktree_id
  // Store agent token for subsequent agent-scoped requests
  if (result.agent_token) {
    client.setAgentToken(result.agent_token)
  }
  // ... rest unchanged
})

server.tool('unregister_agent', ..., async () => {
  // ... existing logic
  client.clearAgentToken()
  // ...
})
```

---

## Step 9: Write tests

**File:** `tests/gateway/test_agent_token_auth.py` (new)

Tests to write:

1. **`test_register_returns_agent_token`** — register an agent, verify response includes `agent_token` field
2. **`test_heartbeat_with_valid_agent_token`** — register, use returned token for heartbeat, expect 200
3. **`test_heartbeat_with_invalid_token_rejected`** — send heartbeat with wrong token, expect 401
4. **`test_heartbeat_with_wrong_worktree_id_rejected`** — register agent A, use A's token to call agent B's heartbeat, expect 403
5. **`test_agent_token_rotates_on_reregistration`** — register, save token, re-register same path, old token should fail
6. **`test_mcp_service_key_passes_middleware`** — request with valid MCP service key + X-MCP-Request passes
7. **`test_invalid_mcp_service_key_rejected`** — request with wrong MCP service key + X-MCP-Request gets 401
8. **`test_agent_cannot_spoof_mcp_header`** — agent token + X-MCP-Request header still requires valid service key
9. **`test_project_api_key_only_works_for_register`** — project API key on non-register agent routes gets 401 (agent token required)

Each test creates a project, registers an agent, and exercises the auth flow end-to-end against the real test DB.

**File:** `tests/gateway/test_route_isolation.py` — update existing tests:

- `test_mcp_server_allowed_on_all_routes` needs to use a valid MCP service key (currently uses `fake-api-key`)
- `test_agent_blocked_from_board_routes` unchanged (agent token still blocked from board routes)

---

## Step 10: Update existing agent tests

**File:** `tests/agent/test_routes.py` (if exists) and `tests/agent/conftest.py`

Existing agent route tests that call heartbeat, start-task, etc. without auth will break. Update test fixtures to:
1. Create a project, get API key
2. Register an agent, get agent token
3. Use agent token in `Authorization: Bearer` header for all subsequent requests

---

## Execution Order

| Order | Step | Files | Depends On |
|---|---|---|---|
| 1 | Model + migration | `src/agent/models.py`, `src/alembic/versions/` | — |
| 2 | Repository method | `src/agent/repository.py` | Step 1 |
| 3 | Settings | `src/shared/config.py` | — |
| 4 | Registration token gen | `src/agent/services.py`, `src/agent/schemas.py` | Steps 1, 2 |
| 5 | Auth dependencies | `src/gateway/auth.py` | Steps 2, 3 |
| 6 | Middleware update | `src/gateway/app.py` | Step 3 |
| 7 | Route auth | `src/agent/routes.py` | Step 5 |
| 8 | MCP server | `mcp-server/src/{client,server,index}.ts` | Step 4 |
| 9 | New tests | `tests/gateway/test_agent_token_auth.py` | Steps 5-7 |
| 10 | Update existing tests | `tests/agent/`, `tests/gateway/` | Steps 6-7 |

Steps 1-3 are independent and can be done in parallel. Steps 4-7 are sequential. Step 8 (MCP) is independent of steps 5-7 but depends on step 4. Steps 9-10 depend on everything else.

---

## Quality Gate

Before PR:
- `make test-gateway` passes
- `make test-agent` passes (if agent tests updated)
- `make lint` passes
- `make typecheck` passes
- `make quality` passes
- Manual verification: register an agent, confirm `agent_token` in response, use it for heartbeat
