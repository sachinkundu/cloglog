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
    expect(tools.search).toBeDefined()
  })
})

describe('search tool', () => {
  it('refuses to call before register_agent — surfaces the same guidance the other project-scoped tools use', async () => {
    const client = mockClient()
    const server = createServer(client)
    const tools = (server as any)._registeredTools
    const result = await tools.search.handler({ query: 'T-1' })
    expect(result.content[0].text).toMatch(/Not registered/)
    expect(client.request).not.toHaveBeenCalled()
  })

  it('after register, calls GET /projects/{pid}/search?q=...', async () => {
    const client = mockClient()
    ;(client.request as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ worktree_id: 'wt-1', project_id: 'proj-1' })
      .mockResolvedValueOnce({ query: 'T-7', total: 0, results: [] })

    const server = createServer(client)
    const tools = (server as any)._registeredTools
    await tools.register_agent.handler({ worktree_path: '/tmp/not-a-repo' })
    const result = await tools.search.handler({ query: 'T-7' })

    expect(client.request).toHaveBeenLastCalledWith(
      'GET', '/api/v1/projects/proj-1/search?q=T-7'
    )
    expect(result.content[0].text).toContain('"total": 0')
  })
})

describe('update_project tool', () => {
  it('lazily resolves project_id via /gateway/me before any register_agent call', async () => {
    // Codex review on PR #270 (round 2): /cloglog init's Step 6a backfill
    // calls update_project before register_agent. requireProject would
    // return "Not registered" and the backfill would silently no-op,
    // leaving repo_url empty and webhook routing broken. Pin: the lazy
    // path resolves project_id from the API key without prior register.
    const client = mockClient()
    ;(client.request as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ id: 'proj-7', name: 'antisocial', repo_url: '' })  // /gateway/me
      .mockResolvedValueOnce({ id: 'proj-7', repo_url: 'https://github.com/o/r' })  // PATCH

    const server = createServer(client)
    const tools = (server as any)._registeredTools

    const result = await tools.update_project.handler({
      repo_url: 'git@github.com:o/r.git',
    })

    expect(client.request).toHaveBeenNthCalledWith(1, 'GET', '/api/v1/gateway/me')
    expect(client.request).toHaveBeenNthCalledWith(
      2,
      'PATCH',
      '/api/v1/projects/proj-7',
      { repo_url: 'git@github.com:o/r.git' }
    )
    expect(result.content[0].text).toContain('"repo_url": "https://github.com/o/r"')
  })

  it('reuses cached project_id after register_agent — no second /gateway/me call', async () => {
    const client = mockClient()
    ;(client.request as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ worktree_id: 'wt-1', project_id: 'proj-7' })  // register
      .mockResolvedValueOnce({ id: 'proj-7' })  // PATCH only — no /gateway/me

    const server = createServer(client)
    const tools = (server as any)._registeredTools
    await tools.register_agent.handler({ worktree_path: '/tmp/x' })
    await tools.update_project.handler({ name: 'renamed' })

    expect(client.request).toHaveBeenCalledTimes(2)
    expect(client.request).toHaveBeenNthCalledWith(2, 'PATCH', '/api/v1/projects/proj-7', {
      name: 'renamed',
    })
    // No /gateway/me call — register_agent already populated currentProjectId.
    const calls = (client.request as ReturnType<typeof vi.fn>).mock.calls
    expect(calls.some((c) => c[1] === '/api/v1/gateway/me')).toBe(false)
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

describe('request_shutdown tool (T-218)', () => {
  it('is registered and posts to the request-shutdown endpoint', async () => {
    const client = mockClient()
    ;(client.request as ReturnType<typeof vi.fn>).mockResolvedValue({ shutdown_requested: true })
    const server = createServer(client)
    const tools = (server as any)._registeredTools

    expect(tools.request_shutdown).toBeDefined()
    const result = await tools.request_shutdown.handler({ worktree_id: 'wt-target' })
    expect(client.request).toHaveBeenCalledWith(
      'POST', '/api/v1/agents/wt-target/request-shutdown'
    )
    expect(result.content[0].text).toContain('"shutdown_requested": true')
  })

  it('is idempotent — second call succeeds with the same payload', async () => {
    const client = mockClient()
    ;(client.request as ReturnType<typeof vi.fn>).mockResolvedValue({ shutdown_requested: true })
    const server = createServer(client)
    const tools = (server as any)._registeredTools

    const r1 = await tools.request_shutdown.handler({ worktree_id: 'wt-target' })
    const r2 = await tools.request_shutdown.handler({ worktree_id: 'wt-target' })
    expect(r1.isError).toBeFalsy()
    expect(r2.isError).toBeFalsy()
    expect(r2.content[0].text).toContain('"shutdown_requested": true')
    expect((client.request as ReturnType<typeof vi.fn>).mock.calls.length).toBe(2)
  })

  it('does NOT require register_agent first (supervisor tool, not agent-scoped)', async () => {
    // Main agent invoking this tool never calls register_agent for itself;
    // the tool must be callable without that prerequisite.
    const client = mockClient()
    ;(client.request as ReturnType<typeof vi.fn>).mockResolvedValue({ shutdown_requested: true })
    const server = createServer(client)
    const tools = (server as any)._registeredTools

    const result = await tools.request_shutdown.handler({ worktree_id: 'wt-foo' })
    expect(result.isError).toBeFalsy()
    expect(result.content[0].text).not.toContain('Not registered')
  })
})

describe('force_unregister tool (T-221)', () => {
  it('is registered and posts to the force-unregister endpoint', async () => {
    const client = mockClient()
    ;(client.request as ReturnType<typeof vi.fn>).mockResolvedValue({
      worktree_id: 'wt-target', already_unregistered: false,
    })
    const server = createServer(client)
    const tools = (server as any)._registeredTools

    expect(tools.force_unregister).toBeDefined()
    const result = await tools.force_unregister.handler({ worktree_id: 'wt-target' })
    expect(client.request).toHaveBeenCalledWith(
      'POST', '/api/v1/agents/wt-target/force-unregister'
    )
    expect(result.content[0].text).toContain('"already_unregistered": false')
  })

  it('handles the already-gone idempotent response', async () => {
    const client = mockClient()
    ;(client.request as ReturnType<typeof vi.fn>).mockResolvedValue({
      worktree_id: 'wt-target', already_unregistered: true,
    })
    const server = createServer(client)
    const tools = (server as any)._registeredTools

    const result = await tools.force_unregister.handler({ worktree_id: 'wt-target' })
    expect(result.isError).toBeFalsy()
    expect(result.content[0].text).toContain('"already_unregistered": true')
  })

  it('description marks it as tier-2 fallback (surfaces the protocol to the caller)', () => {
    const client = mockClient()
    const server = createServer(client)
    const tools = (server as any)._registeredTools
    const description = tools.force_unregister.description as string
    // The reconcile / close-wave rewrites (T-220) read this hint from the
    // MCP tool listing — if the wording drifts, the caller is likely to
    // skip request_shutdown and jump straight to force_unregister.
    expect(description).toMatch(/TIER-2|tier-2/)
    expect(description).toContain('request_shutdown')
    expect(description).toMatch(/first|before/i)
  })
})

describe('list_worktrees tool (T-220)', () => {
  it('requires registration to supply the project_id (no manual project argument)', async () => {
    const client = mockClient()
    const server = createServer(client)
    const tools = (server as any)._registeredTools

    const result = await tools.list_worktrees.handler({})
    // Without register_agent first, requireProject() returns a not-registered
    // error — the supervisor must register itself before querying worktrees.
    expect(result.content[0].text).toContain('Not registered')
  })

  it('posts to GET /projects/{pid}/worktrees after register_agent sets the project', async () => {
    const client = mockClient()
    ;(client.request as ReturnType<typeof vi.fn>).mockResolvedValue({
      worktree_id: 'wt-sup',
      project_id: 'proj-42',
      current_task: null,
      resumed: true,
    })

    const server = createServer(client)
    const tools = (server as any)._registeredTools
    await tools.register_agent.handler({ worktree_path: '/path' })

    ;(client.request as ReturnType<typeof vi.fn>).mockResolvedValue([
      {
        id: 'wt-uuid-1',
        name: 'wt-demo',
        worktree_path: '/abs/path/to/wt-demo',
        branch_name: 'wt-demo',
        status: 'online',
        last_heartbeat: '2026-04-22T08:50:00Z',
      },
    ])

    const result = await tools.list_worktrees.handler({})
    expect(client.request).toHaveBeenCalledWith(
      'GET', '/api/v1/projects/proj-42/worktrees'
    )
    expect(result.content[0].text).toContain('wt-demo')
    expect(result.isError).toBeFalsy()
  })

  it('description explains it survives supervisor restart (the ephemeral-inbox failure mode the PR-182 review caught)', () => {
    const client = mockClient()
    const server = createServer(client)
    const tools = (server as any)._registeredTools
    const description = tools.list_worktrees.description as string
    expect(description).toMatch(/supervisor restart|survives/i)
    expect(description).toContain('worktree_id')
  })
})
