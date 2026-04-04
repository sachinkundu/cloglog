import { describe, it, expect, vi, beforeEach } from 'vitest'
import { CloglogClient } from '../client.js'
import { createToolHandlers, ToolHandlers } from '../tools.js'

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

  it('register_agent calls POST /agents/register', async () => {
    (client.request as ReturnType<typeof vi.fn>).mockResolvedValue({
      worktree_id: 'wt-123',
      name: 'wt-auth',
      current_task: null,
      resumed: false,
    })

    const result = await handlers.register_agent({ worktree_path: '/home/user/wt-auth' })
    expect(client.request).toHaveBeenCalledWith(
      'POST', '/api/v1/agents/register',
      { worktree_path: '/home/user/wt-auth' }
    )
    expect(result).toHaveProperty('worktree_id', 'wt-123')
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

  it('add_task_note calls POST /agents/{wt}/task-note', async () => {
    await handlers.add_task_note({
      worktree_id: 'wt-123', task_id: 't1', note: 'Working on it',
    })
    expect(client.request).toHaveBeenCalledWith(
      'POST', '/api/v1/agents/wt-123/task-note',
      { task_id: 't1', note: 'Working on it' }
    )
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
