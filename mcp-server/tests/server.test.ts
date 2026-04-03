import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createServer } from '../src/server.js'
import { CloglogClient } from '../src/client.js'

function mockClient(): CloglogClient {
  return {
    request: vi.fn().mockResolvedValue({}),
    registerAgent: vi.fn().mockResolvedValue({}),
  } as unknown as CloglogClient
}

describe('createServer', () => {
  it('creates an MCP server with all tools', () => {
    const client = mockClient()
    const server = createServer(client)
    expect(server).toBeTruthy()

    const tools = (server as any)._registeredTools
    expect(tools.register_agent).toBeDefined()
    expect(tools.get_my_tasks).toBeDefined()
    expect(tools.start_task).toBeDefined()
    expect(tools.complete_task).toBeDefined()
    expect(tools.update_task_status).toBeDefined()
    expect(tools.add_task_note).toBeDefined()
    expect(tools.attach_document).toBeDefined()
    expect(tools.create_tasks).toBeDefined()
    expect(tools.unregister_agent).toBeDefined()
  })
})

describe('register_agent tool', () => {
  let client: CloglogClient

  beforeEach(() => {
    client = mockClient()
  })

  it('calls client.request and returns result as text content', async () => {
    const mockResponse = {
      worktree_id: 'wt-abc',
      current_task: { id: 'task-1', title: 'Build feature X' },
      resumed: true,
    }

    ;(client.request as ReturnType<typeof vi.fn>).mockResolvedValue(mockResponse)

    const server = createServer(client)
    const tools = (server as any)._registeredTools
    const result = await tools.register_agent.handler({ worktree_path: '/path/to/worktree' })

    expect(client.request).toHaveBeenCalledWith(
      'POST', '/api/v1/agents/register',
      { worktree_path: '/path/to/worktree' }
    )
    expect(result).toEqual({
      content: [
        {
          type: 'text',
          text: JSON.stringify(mockResponse, null, 2),
        },
      ],
    })
  })
})

describe('unregister_agent tool', () => {
  it('stops heartbeat and unregisters', async () => {
    const client = mockClient()
    ;(client.request as ReturnType<typeof vi.fn>).mockResolvedValue({
      worktree_id: 'wt-abc',
    })

    const server = createServer(client)
    const tools = (server as any)._registeredTools

    // Register first to set worktree ID
    await tools.register_agent.handler({ worktree_path: '/path' })

    // Now unregister
    const result = await tools.unregister_agent.handler({})
    expect(result).toEqual({
      content: [{ type: 'text', text: 'Unregistered wt-abc.' }],
    })
  })
})

describe('tools require registration', () => {
  it('get_my_tasks returns error when not registered', async () => {
    const client = mockClient()
    const server = createServer(client)
    const tools = (server as any)._registeredTools

    const result = await tools.get_my_tasks.handler({})
    expect(result.content[0].text).toContain('Not registered')
  })
})
