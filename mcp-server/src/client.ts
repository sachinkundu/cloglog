/**
 * HTTP client for the cloglog API.
 * Each MCP tool calls methods on this client.
 */

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

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    }

    if (isRegisterRoute || isUnregisterByPath) {
      // Registration/unregister-by-path uses project API key
      headers['Authorization'] = `Bearer ${this.apiKey}`
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
      const text = await response.text()
      throw new Error(`cloglog API error: ${response.status} ${text}`)
    }

    if (response.status === 204 || response.headers.get('content-length') === '0') {
      return { ok: true }
    }

    return response.json()
  }
}
