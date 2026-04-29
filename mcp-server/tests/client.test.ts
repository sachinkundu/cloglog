import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { CloglogClient } from '../src/client.js'

describe('CloglogClient', () => {
  it('constructs with config', () => {
    const client = new CloglogClient({
      baseUrl: 'http://localhost:8000',
      apiKey: 'test-key',
      serviceKey: 'test-service-key',
    })
    expect(client).toBeTruthy()
  })

  it('strips trailing slash from base URL', () => {
    const client = new CloglogClient({
      baseUrl: 'http://localhost:8000/',
      apiKey: 'test-key',
      serviceKey: 'test-service-key',
    })
    expect((client as any).baseUrl).toBe('http://localhost:8000')
  })

  describe('registerAgent', () => {
    let client: CloglogClient

    beforeEach(() => {
      client = new CloglogClient({
        baseUrl: 'http://localhost:8000',
        apiKey: 'test-key',
      serviceKey: 'test-service-key',
      })
    })

    afterEach(() => {
      vi.restoreAllMocks()
    })

    it('sends POST to /api/v1/agents/register with worktree_path', async () => {
      const mockResponse = {
        worktree_id: 'wt-123',
        current_task: null,
        resumed: false,
      }

      vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response(JSON.stringify(mockResponse), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )

      const result = await client.registerAgent('/home/user/project/.git/worktrees/wt-mcp')

      expect(fetch).toHaveBeenCalledWith(
        'http://localhost:8000/api/v1/agents/register',
        expect.objectContaining({
          method: 'POST',
          headers: expect.objectContaining({
            Authorization: 'Bearer test-key',
            'Content-Type': 'application/json',
          }),
          body: JSON.stringify({ worktree_path: '/home/user/project/.git/worktrees/wt-mcp' }),
        }),
      )

      expect(result).toEqual(mockResponse)
    })

    it('throws on API error', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response('Unauthorized', { status: 401 }),
      )

      await expect(
        client.registerAgent('/some/path'),
      ).rejects.toThrow('cloglog API error: 401')
    })
  })

  describe('gateway/me routing', () => {
    let client: CloglogClient

    beforeEach(() => {
      client = new CloglogClient({
        baseUrl: 'http://localhost:8000',
        apiKey: 'test-key',
        serviceKey: 'test-service-key',
      })
    })

    afterEach(() => {
      vi.restoreAllMocks()
    })

    it('uses project API key in Authorization AND X-MCP-Request: true', async () => {
      // Codex review on PR #270 — round 3 catch: /api/v1/gateway/me is
      // protected by ``CurrentProject`` (project API key in Authorization),
      // not the MCP service key. Round 4 catch: the *middleware* still
      // requires ``X-MCP-Request: true`` to let any non-/agents/* route
      // pass; bearer-only is rejected at the middleware before
      // ``CurrentProject`` runs. Both headers are required together —
      // the canonical shape pinned by tests/e2e/test_full_workflow.py.
      vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response(JSON.stringify({ id: 'proj-1', name: 'p' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )

      await client.request('GET', '/api/v1/gateway/me')

      const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0]
      expect(call[0]).toBe('http://localhost:8000/api/v1/gateway/me')
      const headers = call[1].headers as Record<string, string>
      expect(headers.Authorization).toBe('Bearer test-key')
      expect(headers['X-MCP-Request']).toBe('true')
    })
  })


  describe('assign-task routing', () => {
    let client: CloglogClient

    beforeEach(() => {
      client = new CloglogClient({
        baseUrl: 'http://localhost:8000',
        apiKey: 'test-key',
        serviceKey: 'test-service-key',
      })
      client.setAgentToken('caller-agent-token')
    })

    afterEach(() => {
      vi.restoreAllMocks()
    })

    it('uses MCP service key (not agent token) for assign-task', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response(JSON.stringify({ status: 'assigned' }), { status: 200 }),
      )

      await client.request('PATCH', '/api/v1/agents/target-wt/assign-task', {
        task_id: 't1',
      })

      expect(fetch).toHaveBeenCalledWith(
        'http://localhost:8000/api/v1/agents/target-wt/assign-task',
        expect.objectContaining({
          headers: expect.objectContaining({
            Authorization: 'Bearer test-service-key',
            'X-MCP-Request': 'true',
          }),
        }),
      )
    })

    it('still uses agent token for self-scoped agent routes', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response(JSON.stringify({ status: 'ok' }), { status: 200 }),
      )

      await client.request('POST', '/api/v1/agents/caller-wt/heartbeat')

      expect(fetch).toHaveBeenCalledWith(
        'http://localhost:8000/api/v1/agents/caller-wt/heartbeat',
        expect.objectContaining({
          headers: expect.objectContaining({
            Authorization: 'Bearer caller-agent-token',
          }),
        }),
      )
    })

    it('uses MCP service key for request-shutdown (T-218 supervisor tool)', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response(JSON.stringify({ shutdown_requested: true }), { status: 200 }),
      )

      await client.request('POST', '/api/v1/agents/target-wt/request-shutdown')

      expect(fetch).toHaveBeenCalledWith(
        'http://localhost:8000/api/v1/agents/target-wt/request-shutdown',
        expect.objectContaining({
          headers: expect.objectContaining({
            Authorization: 'Bearer test-service-key',
            'X-MCP-Request': 'true',
          }),
        }),
      )
    })

    it('uses MCP service key for force-unregister (T-221 supervisor tool, agent tokens rejected)', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response(JSON.stringify({ already_unregistered: false }), { status: 200 }),
      )

      await client.request('POST', '/api/v1/agents/target-wt/force-unregister')

      expect(fetch).toHaveBeenCalledWith(
        'http://localhost:8000/api/v1/agents/target-wt/force-unregister',
        expect.objectContaining({
          headers: expect.objectContaining({
            Authorization: 'Bearer test-service-key',
            'X-MCP-Request': 'true',
          }),
        }),
      )
    })

    it('uses project API key (not agent token) for /agents/close-off-task', async () => {
      // T-246: close-off-task creation is a project-scoped bootstrap call
      // (like /agents/register and /agents/unregister-by-path) — the caller
      // does not yet have a per-agent token, so the project API key must win
      // over any cached agent token.
      vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response(
          JSON.stringify({ task_id: 't-1', task_number: 42, worktree_id: 'wt-1', worktree_name: 'wt-x', created: true }),
          { status: 201, headers: { 'Content-Type': 'application/json' } },
        ),
      )

      await client.request('POST', '/api/v1/agents/close-off-task', {
        worktree_path: '/tmp/wt-x',
        worktree_name: 'wt-x',
      })

      const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0]
      expect(call[0]).toBe('http://localhost:8000/api/v1/agents/close-off-task')
      const opts = call[1] as RequestInit
      const headers = opts.headers as Record<string, string>
      expect(headers.Authorization).toBe('Bearer test-key')
      expect(headers['X-MCP-Request']).toBeUndefined()
    })
  })
})
