import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createServer } from '../src/server.js'
import { CloglogClient } from '../src/client.js'

describe('createServer', () => {
  it('creates an MCP server with register_agent tool', () => {
    const client = new CloglogClient({
      baseUrl: 'http://localhost:8000',
      apiKey: 'test-key',
    })

    const server = createServer(client)
    expect(server).toBeTruthy()
  })
})

describe('register_agent tool', () => {
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

  it('calls client.registerAgent and returns result as text content', async () => {
    const mockResponse = {
      worktree_id: 'wt-abc',
      current_task: { id: 'task-1', title: 'Build feature X' },
      resumed: true,
    }

    vi.spyOn(client, 'registerAgent').mockResolvedValue(mockResponse)

    const server = createServer(client)

    // Access the registered tool handler via the server's internal registry
    const tools = (server as any)._registeredTools
    expect(tools).toBeDefined()
    expect(tools.register_agent).toBeDefined()

    // Call the tool handler directly
    const toolEntry = tools.register_agent
    const result = await toolEntry.handler({ worktree_path: '/path/to/worktree' })

    expect(client.registerAgent).toHaveBeenCalledWith('/path/to/worktree')
    expect(result).toEqual({
      content: [
        {
          type: 'text',
          text: JSON.stringify(mockResponse, null, 2),
        },
      ],
    })
  })

  it('returns error content when client throws', async () => {
    vi.spyOn(client, 'registerAgent').mockRejectedValue(
      new Error('cloglog API error: 500 Internal Server Error'),
    )

    const server = createServer(client)
    const tools = (server as any)._registeredTools
    const result = await tools.register_agent.handler({ worktree_path: '/path' })

    expect(result).toEqual({
      isError: true,
      content: [
        {
          type: 'text',
          text: 'cloglog API error: 500 Internal Server Error',
        },
      ],
    })
  })
})
