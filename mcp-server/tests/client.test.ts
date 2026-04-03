import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { CloglogClient } from '../src/client.js'

describe('CloglogClient', () => {
  it('constructs with config', () => {
    const client = new CloglogClient({
      baseUrl: 'http://localhost:8000',
      apiKey: 'test-key',
    })
    expect(client).toBeTruthy()
  })

  it('strips trailing slash from base URL', () => {
    const client = new CloglogClient({
      baseUrl: 'http://localhost:8000/',
      apiKey: 'test-key',
    })
    expect((client as any).baseUrl).toBe('http://localhost:8000')
  })

  describe('registerAgent', () => {
    let client: CloglogClient

    beforeEach(() => {
      client = new CloglogClient({
        baseUrl: 'http://localhost:8000',
        apiKey: 'test-key',
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
})
