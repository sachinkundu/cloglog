import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { CloglogClient } from '../client.js'
import { createToolHandlers, ToolHandlers, deriveBranchName } from '../tools.js'

function mockClient(): CloglogClient {
  return {
    request: vi.fn().mockResolvedValue({}),
  } as unknown as CloglogClient
}

describe('Tool Handlers', () => {
  let client: CloglogClient
  let handlers: ToolHandlers

  beforeEach(() => {
    client = mockClient()
    handlers = createToolHandlers(client)
  })

  it('register_agent derives branch_name via git and POSTs both to /agents/register', async () => {
    // T-254: cloglog-mcp is the caller sitting inside the worktree, so it
    // resolves the branch and POSTs it. The backend is a thin CRUD layer
    // that stores whatever it receives; if the MCP sends an empty string
    // the webhook branch-fallback has nothing to route on.
    const tmp = mkdtempSync(join(tmpdir(), 'wt-register-test-'))
    try {
      execFileSync('git', ['init', '-q', '-b', 'wt-from-mcp', tmp])

      ;(client.request as ReturnType<typeof vi.fn>).mockResolvedValue({
        worktree_id: 'wt-123',
        name: 'wt-from-mcp',
        current_task: null,
        resumed: false,
      })

      const result = await handlers.register_agent({ worktree_path: tmp })
      expect(client.request).toHaveBeenCalledWith(
        'POST', '/api/v1/agents/register',
        { worktree_path: tmp, branch_name: 'wt-from-mcp' }
      )
      expect(result).toHaveProperty('worktree_id', 'wt-123')
    } finally {
      rmSync(tmp, { recursive: true, force: true })
    }
  })

  it('register_agent sends empty branch_name when the path is not a git repo', async () => {
    // Safety net for the edge case: even if derivation fails, registration
    // must still succeed end-to-end — the backend resolver's empty-branch
    // short-circuit handles the empty value downstream.
    ;(client.request as ReturnType<typeof vi.fn>).mockResolvedValue({
      worktree_id: 'wt-456',
      name: 'wt-bogus',
      current_task: null,
      resumed: false,
    })

    await handlers.register_agent({ worktree_path: '/nonexistent/not-a-repo' })
    expect(client.request).toHaveBeenCalledWith(
      'POST', '/api/v1/agents/register',
      { worktree_path: '/nonexistent/not-a-repo', branch_name: '' }
    )
  })

  it('deriveBranchName returns "" on detached HEAD rather than a sha', () => {
    // `git symbolic-ref --short HEAD` is chosen over `rev-parse --abbrev-ref
    // HEAD` specifically because detached HEAD exits non-zero instead of
    // returning the literal string "HEAD". Pins that contract.
    const tmp = mkdtempSync(join(tmpdir(), 'wt-detached-test-'))
    try {
      const gitEnv = {
        ...process.env,
        GIT_AUTHOR_NAME: 't',
        GIT_AUTHOR_EMAIL: 't@t',
        GIT_COMMITTER_NAME: 't',
        GIT_COMMITTER_EMAIL: 't@t',
      }
      execFileSync('git', ['init', '-q', '-b', 'main', tmp])
      execFileSync('git', ['-C', tmp, 'commit', '--allow-empty', '-m', 'init'], { env: gitEnv })
      execFileSync('git', ['-C', tmp, 'checkout', '--detach', 'HEAD'], {
        env: gitEnv,
        stdio: 'ignore',
      })

      expect(deriveBranchName(tmp)).toBe('')
    } finally {
      rmSync(tmp, { recursive: true, force: true })
    }
  })

  it('get_my_tasks calls GET /agents/{wt}/tasks', async () => {
    (client.request as ReturnType<typeof vi.fn>).mockResolvedValue([
      { task_id: 't1', title: 'Write tests', status: 'backlog' },
    ])

    const result = await handlers.get_my_tasks({ worktree_id: 'wt-123' })
    expect(client.request).toHaveBeenCalledWith('GET', '/api/v1/agents/wt-123/tasks')
    expect(result).toHaveLength(1)
  })

  it('start_task calls POST /agents/{wt}/start-task', async () => {
    await handlers.start_task({ worktree_id: 'wt-123', task_id: 't1' })
    expect(client.request).toHaveBeenCalledWith(
      'POST', '/api/v1/agents/wt-123/start-task',
      { task_id: 't1' }
    )
  })

  it('complete_task calls POST /agents/{wt}/complete-task', async () => {
    (client.request as ReturnType<typeof vi.fn>).mockResolvedValue({
      completed_task_id: 't1',
      next_task: null,
    })

    const result = await handlers.complete_task({ worktree_id: 'wt-123', task_id: 't1' })
    expect(client.request).toHaveBeenCalledWith(
      'POST', '/api/v1/agents/wt-123/complete-task',
      { task_id: 't1' }
    )
    expect(result).toHaveProperty('completed_task_id', 't1')
  })

  it('update_task_status calls PATCH /agents/{wt}/task-status', async () => {
    await handlers.update_task_status({
      worktree_id: 'wt-123', task_id: 't1', status: 'review',
    })
    expect(client.request).toHaveBeenCalledWith(
      'PATCH', '/api/v1/agents/wt-123/task-status',
      { task_id: 't1', status: 'review' }
    )
  })

  it('attach_document calls POST /documents with entity_type and entity_id', async () => {
    await handlers.attach_document({
      entity_type: 'feature',
      entity_id: 'f1',
      type: 'spec',
      title: 'Auth Spec',
      content: '# Auth\n\nSpec content.',
      source_path: 'docs/auth.md',
    })
    expect(client.request).toHaveBeenCalledWith(
      'POST', '/api/v1/documents',
      {
        attached_to_type: 'feature',
        attached_to_id: 'f1',
        doc_type: 'spec',
        title: 'Auth Spec',
        content: '# Auth\n\nSpec content.',
        source_path: 'docs/auth.md',
      }
    )
  })

  it('unregister_agent calls POST /agents/{wt}/unregister', async () => {
    await handlers.unregister_agent({ worktree_id: 'wt-123' })
    expect(client.request).toHaveBeenCalledWith(
      'POST', '/api/v1/agents/wt-123/unregister'
    )
  })

  it('request_shutdown (T-218) calls POST /agents/{wt}/request-shutdown', async () => {
    await handlers.request_shutdown({ worktree_id: 'wt-123' })
    expect(client.request).toHaveBeenCalledWith(
      'POST', '/api/v1/agents/wt-123/request-shutdown'
    )
  })

  it('force_unregister (T-221) calls POST /agents/{wt}/force-unregister', async () => {
    await handlers.force_unregister({ worktree_id: 'wt-123' })
    expect(client.request).toHaveBeenCalledWith(
      'POST', '/api/v1/agents/wt-123/force-unregister'
    )
  })

  it('add_task_note calls POST /agents/{wt}/task-note', async () => {
    await handlers.add_task_note({
      worktree_id: 'wt-123', task_id: 't1', note: 'Working on it',
    })
    expect(client.request).toHaveBeenCalledWith(
      'POST', '/api/v1/agents/wt-123/task-note',
      { task_id: 't1', note: 'Working on it' }
    )
  })

  it('get_board calls GET /projects/{id}/board with no params by default', async () => {
    await handlers.get_board({ project_id: 'proj-1' })
    expect(client.request).toHaveBeenCalledWith(
      'GET', '/api/v1/projects/proj-1/board'
    )
  })

  it('get_board passes epic_id and exclude_done as query params', async () => {
    await handlers.get_board({ project_id: 'proj-1', epic_id: 'epic-1', exclude_done: true })
    expect(client.request).toHaveBeenCalledWith(
      'GET', '/api/v1/projects/proj-1/board?epic_id=epic-1&exclude_done=true'
    )
  })

  it('assign_task calls PATCH /agents/{wt}/assign-task', async () => {
    (client.request as ReturnType<typeof vi.fn>).mockResolvedValue({
      task_id: 't1',
      worktree_id: 'wt-target',
      status: 'assigned',
    })

    const result = await handlers.assign_task({ worktree_id: 'wt-target', task_id: 't1' })
    expect(client.request).toHaveBeenCalledWith(
      'PATCH', '/api/v1/agents/wt-target/assign-task',
      { task_id: 't1' }
    )
    expect(result).toHaveProperty('status', 'assigned')
  })

  it('update_epic calls PATCH /epics/{id}', async () => {
    (client.request as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 'epic-1', title: 'Updated Epic',
    })

    const result = await handlers.update_epic({ epic_id: 'epic-1', title: 'Updated Epic' })
    expect(client.request).toHaveBeenCalledWith(
      'PATCH', '/api/v1/epics/epic-1',
      { title: 'Updated Epic' }
    )
    expect(result).toHaveProperty('title', 'Updated Epic')
  })

  it('delete_epic calls DELETE /epics/{id}', async () => {
    await handlers.delete_epic({ epic_id: 'epic-1' })
    expect(client.request).toHaveBeenCalledWith(
      'DELETE', '/api/v1/epics/epic-1'
    )
  })

  it('update_feature calls PATCH /features/{id}', async () => {
    (client.request as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 'feat-1', title: 'Updated Feature',
    })

    const result = await handlers.update_feature({ feature_id: 'feat-1', title: 'Updated Feature' })
    expect(client.request).toHaveBeenCalledWith(
      'PATCH', '/api/v1/features/feat-1',
      { title: 'Updated Feature' }
    )
    expect(result).toHaveProperty('title', 'Updated Feature')
  })

  it('delete_feature calls DELETE /features/{id}', async () => {
    await handlers.delete_feature({ feature_id: 'feat-1' })
    expect(client.request).toHaveBeenCalledWith(
      'DELETE', '/api/v1/features/feat-1'
    )
  })

  it('get_active_tasks calls GET /projects/{id}/active-tasks', async () => {
    (client.request as ReturnType<typeof vi.fn>).mockResolvedValue([
      { id: 't1', number: 1, title: 'Task 1', status: 'backlog' },
    ])

    const result = await handlers.get_active_tasks({ project_id: 'proj-1' })
    expect(client.request).toHaveBeenCalledWith(
      'GET', '/api/v1/projects/proj-1/active-tasks'
    )
    expect(result).toHaveLength(1)
  })

  it('create_task passes task_type to the API', async () => {
    (client.request as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 't-new', title: 'Write spec', task_type: 'spec',
    })

    const result = await handlers.create_task({
      project_id: 'proj-1',
      feature_id: 'f1',
      title: 'Write spec',
      task_type: 'spec',
    })
    expect(client.request).toHaveBeenCalledWith(
      'POST', '/api/v1/projects/proj-1/features/f1/tasks',
      { title: 'Write spec', description: '', priority: 'normal', task_type: 'spec' }
    )
    expect(result).toHaveProperty('task_type', 'spec')
  })

  it('create_task defaults task_type to "task"', async () => {
    (client.request as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 't-new', title: 'Fix bug',
    })

    await handlers.create_task({
      project_id: 'proj-1',
      feature_id: 'f1',
      title: 'Fix bug',
    })
    expect(client.request).toHaveBeenCalledWith(
      'POST', '/api/v1/projects/proj-1/features/f1/tasks',
      { title: 'Fix bug', description: '', priority: 'normal', task_type: 'task' }
    )
  })

  it('update_task_status passes pr_url when provided', async () => {
    await handlers.update_task_status({
      worktree_id: 'wt-123', task_id: 't1', status: 'review',
      pr_url: 'https://github.com/org/repo/pull/42',
    })
    expect(client.request).toHaveBeenCalledWith(
      'PATCH', '/api/v1/agents/wt-123/task-status',
      { task_id: 't1', status: 'review', pr_url: 'https://github.com/org/repo/pull/42' }
    )
  })

  it('complete_task passes pr_url when provided', async () => {
    (client.request as ReturnType<typeof vi.fn>).mockResolvedValue({
      completed_task_id: 't1', next_task: null,
    })

    await handlers.complete_task({
      worktree_id: 'wt-123', task_id: 't1',
      pr_url: 'https://github.com/org/repo/pull/42',
    })
    expect(client.request).toHaveBeenCalledWith(
      'POST', '/api/v1/agents/wt-123/complete-task',
      { task_id: 't1', pr_url: 'https://github.com/org/repo/pull/42' }
    )
  })

  it('add_dependency calls POST /features/{id}/dependencies', async () => {
    (client.request as ReturnType<typeof vi.fn>).mockResolvedValue({ status: 'created' })

    const result = await handlers.add_dependency({ feature_id: 'feat-1', depends_on_id: 'feat-2' })
    expect(client.request).toHaveBeenCalledWith(
      'POST', '/api/v1/features/feat-1/dependencies',
      { depends_on_id: 'feat-2' }
    )
    expect(result).toHaveProperty('status', 'created')
  })

  it('remove_dependency calls DELETE /features/{id}/dependencies/{depends_on_id}', async () => {
    (client.request as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true })

    await handlers.remove_dependency({ feature_id: 'feat-1', depends_on_id: 'feat-2' })
    expect(client.request).toHaveBeenCalledWith(
      'DELETE', '/api/v1/features/feat-1/dependencies/feat-2'
    )
  })

  it('add_dependency propagates API errors (cycle detection)', async () => {
    (client.request as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error('cloglog API error: 400 Adding this dependency would create a cycle')
    )

    await expect(
      handlers.add_dependency({ feature_id: 'feat-1', depends_on_id: 'feat-2' })
    ).rejects.toThrow('cycle')
  })

  it('add_dependency propagates API errors (duplicate)', async () => {
    (client.request as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error('cloglog API error: 409 Dependency already exists')
    )

    await expect(
      handlers.add_dependency({ feature_id: 'feat-1', depends_on_id: 'feat-2' })
    ).rejects.toThrow('409')
  })

  it('remove_dependency propagates API errors (not found)', async () => {
    (client.request as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error('cloglog API error: 404 Dependency not found')
    )

    await expect(
      handlers.remove_dependency({ feature_id: 'feat-1', depends_on_id: 'feat-2' })
    ).rejects.toThrow('404')
  })

  it('add_task_dependency calls POST /tasks/{id}/dependencies', async () => {
    (client.request as ReturnType<typeof vi.fn>).mockResolvedValue({ status: 'created' })

    const result = await handlers.add_task_dependency({ task_id: 't-1', depends_on_id: 't-2' })
    expect(client.request).toHaveBeenCalledWith(
      'POST', '/api/v1/tasks/t-1/dependencies',
      { depends_on_id: 't-2' }
    )
    expect(result).toHaveProperty('status', 'created')
  })

  it('remove_task_dependency calls DELETE /tasks/{id}/dependencies/{depends_on_id}', async () => {
    (client.request as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true })

    await handlers.remove_task_dependency({ task_id: 't-1', depends_on_id: 't-2' })
    expect(client.request).toHaveBeenCalledWith(
      'DELETE', '/api/v1/tasks/t-1/dependencies/t-2'
    )
  })

  it('add_task_dependency propagates API errors (cycle)', async () => {
    (client.request as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error('cloglog API error: 400 Adding this dependency would create a cycle')
    )
    await expect(
      handlers.add_task_dependency({ task_id: 't-1', depends_on_id: 't-2' })
    ).rejects.toThrow('cycle')
  })

  it('start_task propagates API errors (guard rejections)', async () => {
    (client.request as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error('cloglog API error: 409 Cannot start task: agent already has active task(s)')
    )

    await expect(
      handlers.start_task({ worktree_id: 'wt-123', task_id: 't1' })
    ).rejects.toThrow('409')
  })

  it('update_task_status propagates API errors (pr_url required)', async () => {
    (client.request as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error('cloglog API error: 409 Cannot move task to review without a PR URL')
    )

    await expect(
      handlers.update_task_status({
        worktree_id: 'wt-123', task_id: 't1', status: 'review',
      })
    ).rejects.toThrow('409')
  })

  it('complete_task propagates API errors (agents cannot mark done)', async () => {
    (client.request as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error('cloglog API error: 409 Agents cannot mark tasks as done')
    )

    await expect(
      handlers.complete_task({ worktree_id: 'wt-123', task_id: 't1' })
    ).rejects.toThrow('Agents cannot mark tasks as done')
  })

  it('create_tasks calls POST /projects/{id}/import', async () => {
    (client.request as ReturnType<typeof vi.fn>).mockResolvedValue({
      epics_created: 1, features_created: 2, tasks_created: 5,
    })

    const result = await handlers.create_tasks({
      project_id: 'proj-1',
      epics: [{ title: 'E1', features: [{ title: 'F1', tasks: [{ title: 'T1' }] }] }],
    })
    expect(client.request).toHaveBeenCalledWith(
      'POST', '/api/v1/projects/proj-1/import',
      { epics: [{ title: 'E1', features: [{ title: 'F1', tasks: [{ title: 'T1' }] }] }] }
    )
    expect(result).toHaveProperty('epics_created', 1)
  })
})
