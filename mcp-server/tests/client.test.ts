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
  })
})
