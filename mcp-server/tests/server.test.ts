import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createServer } from '../src/server.js'
import { CloglogClient } from '../src/client.js'

function mockClient(): CloglogClient {
  return {
    request: vi.fn().mockResolvedValue({}),
    registerAgent: vi.fn().mockResolvedValue({}),
    setAgentToken: vi.fn(),
    clearAgentToken: vi.fn(),
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
      project_id: 'proj-1',
      current_task: { id: 'task-1', title: 'Build feature X' },
      resumed: true,
    }

    ;(client.request as ReturnType<typeof vi.fn>).mockResolvedValue(mockResponse)

    const server = createServer(client)
    const tools = (server as any)._registeredTools
    const result = await tools.register_agent.handler({ worktree_path: '/path/to/worktree' })

    // T-254: register_agent derives branch_name in-VM and sends it with the
    // path. The path here is not a real git repo, so branch_name comes back
    // empty — which is the exact fallback the backend resolver guards handle.
    expect(client.request).toHaveBeenCalledWith(
      'POST', '/api/v1/agents/register',
      { worktree_path: '/path/to/worktree', branch_name: '' }
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
      project_id: 'proj-1',
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

describe('guard error handling', () => {
  let client: CloglogClient
  let tools: any

  beforeEach(async () => {
    client = mockClient()
    ;(client.request as ReturnType<typeof vi.fn>).mockResolvedValue({
      worktree_id: 'wt-abc',
      project_id: 'proj-1',
    })

    const server = createServer(client)
    tools = (server as any)._registeredTools
    // Register first
    await tools.register_agent.handler({ worktree_path: '/path' })
  })

  it('start_task returns isError when guard rejects (one active task)', async () => {
    ;(client.request as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error('cloglog API error: 409 {"detail":"Cannot start task: agent already has active task(s): T-10 \'Write spec\' (in_progress)"}')
    )

    const result = await tools.start_task.handler({ task_id: 't1' })
    expect(result.isError).toBe(true)
    expect(result.content[0].text).toContain('Cannot start task')
  })

  it('start_task returns isError when pipeline guard rejects', async () => {
    ;(client.request as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error('cloglog API error: 409 {"detail":"Cannot start plan task: spec task(s) not done yet"}')
    )

    const result = await tools.start_task.handler({ task_id: 't1' })
    expect(result.isError).toBe(true)
    expect(result.content[0].text).toContain('spec task')
  })

  it('update_task_status returns isError when pr_url missing for review', async () => {
    ;(client.request as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error('cloglog API error: 409 {"detail":"Cannot move task to review without a PR URL"}')
    )

    const result = await tools.update_task_status.handler({ task_id: 't1', status: 'review' })
    expect(result.isError).toBe(true)
    expect(result.content[0].text).toContain('PR URL')
  })

  it('update_task_status describes webhook inbox events (not a polling loop) when moving to review with pr_url', async () => {
    ;(client.request as ReturnType<typeof vi.fn>).mockResolvedValueOnce({})

    const result = await tools.update_task_status.handler({
      task_id: 't1', status: 'review',
      pr_url: 'https://github.com/org/repo/pull/99',
    })
    expect(result.isError).toBeFalsy()
    const text = result.content[0].text
    expect(text).toContain('moved to review')
    expect(text).toContain('CRITICAL')
    expect(text).toContain('PR #99')
    expect(text).toContain('webhook')
    expect(text).toContain('inbox')
    expect(text).toContain('review_submitted')
    expect(text).toContain('review_comment')
    expect(text).toContain('issue_comment')
    expect(text).toContain('ci_failed')
    expect(text).toContain('pr_merged')
    expect(text).toContain('event does NOT include task_id')
    // The old /loop instruction is gone — webhooks replace polling
    expect(text).not.toContain('/loop 5m')
    expect(text).toContain('Do NOT start a /loop')
  })

  it('update_task_status does NOT include webhook guidance for non-review status', async () => {
    ;(client.request as ReturnType<typeof vi.fn>).mockResolvedValueOnce({})

    const result = await tools.update_task_status.handler({
      task_id: 't1', status: 'in_progress',
    })
    expect(result.isError).toBeFalsy()
    const text = result.content[0].text
    expect(text).toContain('moved to in_progress')
    expect(text).not.toContain('/loop')
    expect(text).not.toContain('webhook')
    expect(text).not.toContain('inbox')
  })

  it('update_task_status returns isError when agent tries done', async () => {
    ;(client.request as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error('cloglog API error: 409 {"detail":"Agents cannot mark tasks as done"}')
    )

    const result = await tools.update_task_status.handler({ task_id: 't1', status: 'done' })
    expect(result.isError).toBe(true)
    expect(result.content[0].text).toContain('Agents cannot mark tasks as done')
  })

  it('complete_task returns isError (agents cannot mark done)', async () => {
    ;(client.request as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error('cloglog API error: 409 {"detail":"Agents cannot mark tasks as done"}')
    )

    const result = await tools.complete_task.handler({ task_id: 't1' })
    expect(result.isError).toBe(true)
    expect(result.content[0].text).toContain('Agents cannot mark tasks as done')
  })
})
