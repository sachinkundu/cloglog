/**
 * HTTP client for the cloglog API.
 * Each MCP tool calls methods on this client.
 */

import { CloglogApiError, type ErrorDetail, type StructuredDetail } from './errors.js'

export { CloglogApiError } from './errors.js'

export interface CloglogClientConfig {
  baseUrl: string
  apiKey: string
  serviceKey: string
}

export interface RegisterAgentResult {
  worktree_id: string
  project_id: string
  current_task: { id: string; title: string } | null
  resumed: boolean
  agent_token: string
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

  setAgentToken(token: string): void {
    this.agentToken = token
  }

  clearAgentToken(): void {
    this.agentToken = null
  }

  getBaseUrl(): string {
    return this.baseUrl
  }

  async registerAgent(worktreePath: string): Promise<RegisterAgentResult> {
    return this.request('POST', '/api/v1/agents/register', {
      worktree_path: worktreePath,
    }) as Promise<RegisterAgentResult>
  }

  async request(method: string, path: string, body?: unknown): Promise<unknown> {
    const url = `${this.baseUrl}${path}`
    const isAgentRoute = path.startsWith('/api/v1/agents/')
    const isRegisterRoute = path === '/api/v1/agents/register'
    const isUnregisterByPath = path === '/api/v1/agents/unregister-by-path'
    // T-246: create_close_off_task is a launch-skill / worktree-bootstrap
    // operation that authenticates as the project, not as a specific agent —
    // the caller knows the worktree by path before any agent session owns a
    // token. Route it like register_agent / unregister-by-path.
    const isCloseOffTaskRoute = path === '/api/v1/agents/close-off-task'
    // T-346: GET /api/v1/gateway/me is protected by ``CurrentProject`` (the
    // project API key), not the MCP service key. The MCP server hits this
    // endpoint from ``ensureProject()`` to lazy-resolve project_id during
    // ``/cloglog init``'s repo_url backfill — before any agent registers.
    // Without the project-API-key route, ``ensureProject()`` 401s and the
    // backfill silently no-ops.
    const isGatewayMeRoute = path === '/api/v1/gateway/me'
    // Supervisor routes target a different worktree than the caller — the
    // caller's agent token (which is bound to its own worktree) would fail
    // the target-worktree check. Use the MCP service key instead.
    //
    // ``/force-unregister`` (T-221) also *rejects* agent tokens at the
    // backend; sending the MCP service key here is what makes the tool
    // callable from the supervising agent even when no agent token exists.
    const SUPERVISOR_SUFFIXES = ['/assign-task', '/request-shutdown', '/force-unregister']
    const isSupervisorRoute =
      isAgentRoute && SUPERVISOR_SUFFIXES.some((s) => path.endsWith(s))

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    }

    if (isRegisterRoute || isUnregisterByPath || isCloseOffTaskRoute) {
      // Project-scoped agent bootstrap/teardown routes use project API key
      headers['Authorization'] = `Bearer ${this.apiKey}`
    } else if (isGatewayMeRoute) {
      // GET /api/v1/gateway/me is protected by ``CurrentProject`` (project
      // API key in Authorization), but the *middleware* still requires the
      // ``X-MCP-Request`` header to let any non-/agents/* route through
      // (path 1 in ``ApiAccessControlMiddleware``). Bearer-only is rejected
      // at the middleware before ``CurrentProject`` runs (codex review on
      // PR #270 round 4). Send both headers together — the canonical shape
      // already pinned by ``tests/e2e/test_full_workflow.py``.
      headers['Authorization'] = `Bearer ${this.apiKey}`
      headers['X-MCP-Request'] = 'true'
    } else if (isSupervisorRoute) {
      // Supervisor actions target another worktree — use MCP service key
      headers['Authorization'] = `Bearer ${this.serviceKey}`
      headers['X-MCP-Request'] = 'true'
    } else if (isAgentRoute && this.agentToken) {
      // Agent-scoped routes use per-agent token (no X-MCP-Request)
      headers['Authorization'] = `Bearer ${this.agentToken}`
    } else {
      // Board/document routes use MCP service key
      headers['Authorization'] = `Bearer ${this.serviceKey}`
      headers['X-MCP-Request'] = 'true'
    }

    const response = await fetch(url, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    })

    if (!response.ok) {
      const contentType = response.headers.get('content-type') ?? ''
      // Preserve structured JSON bodies so MCP tool handlers can switch
      // on ``detail.code`` (e.g. ``task_blocked``) — flattening to a
      // string discards the structured blocker payload F-11 depends on.
      if (contentType.includes('application/json')) {
        let body: unknown
        try {
          body = await response.json()
        } catch {
          throw new CloglogApiError(response.status, await response.text())
        }
        const detail: ErrorDetail | undefined =
          body && typeof body === 'object' && 'detail' in body
            ? ((body as { detail?: ErrorDetail }).detail ?? (body as StructuredDetail))
            : (body as StructuredDetail)
        throw new CloglogApiError(response.status, detail ?? JSON.stringify(body))
      }
      const text = await response.text()
      throw new CloglogApiError(response.status, text)
    }

    if (response.status === 204 || response.headers.get('content-length') === '0') {
      return { ok: true }
    }

    return response.json()
  }
}
