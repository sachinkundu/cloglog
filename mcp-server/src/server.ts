import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { z } from 'zod'
import { CloglogClient } from './client.js'
import { HeartbeatTimer } from './heartbeat.js'
import { createToolHandlers } from './tools.js'

export function createServer(client: CloglogClient): McpServer {
  const handlers = createToolHandlers(client)
  let currentWorktreeId: string | null = null
  let currentProjectId: string | null = null
  const heartbeat = new HeartbeatTimer(async () => {
    if (currentWorktreeId) {
      await client.request('POST', `/api/v1/agents/${currentWorktreeId}/heartbeat`)
    }
  })

  const server = new McpServer({
    name: 'cloglog-mcp',
    version: '0.2.0',
  })

  // Helper for tools that require registration
  function requireRegistered(): string | { content: Array<{ type: 'text'; text: string }> } {
    if (!currentWorktreeId) {
      return { content: [{ type: 'text' as const, text: 'Error: Not registered. Call register_agent first.' }] }
    }
    return currentWorktreeId
  }

  function requireProject(): string | { content: Array<{ type: 'text'; text: string }> } {
    if (!currentProjectId) {
      return { content: [{ type: 'text' as const, text: 'Error: Not registered. Call register_agent first.' }] }
    }
    return currentProjectId
  }

  // ── Agent lifecycle ───────────────────────────────────

  server.tool(
    'register_agent',
    'Register this worktree with cloglog. Called at session start. Returns current task if resuming.',
    { worktree_path: z.string().describe('Absolute path to the git worktree') },
    async ({ worktree_path }) => {
      const result = await handlers.register_agent({ worktree_path }) as Record<string, unknown>
      currentWorktreeId = result.worktree_id as string
      // Get project ID from the auth token
      const project = await handlers.get_project({}) as Record<string, unknown>
      currentProjectId = project.id as string
      heartbeat.start()
      return { content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }] }
    }
  )

  server.tool(
    'unregister_agent',
    'Sign off cleanly when session ends.',
    {},
    async () => {
      const wt = requireRegistered()
      if (typeof wt !== 'string') return wt
      heartbeat.stop()
      await handlers.unregister_agent({ worktree_id: wt })
      currentWorktreeId = null
      currentProjectId = null
      return { content: [{ type: 'text' as const, text: `Unregistered ${wt}.` }] }
    }
  )

  // ── Task lifecycle ────────────────────────────────────

  server.tool(
    'get_my_tasks',
    'Get ordered list of tasks assigned to this worktree.',
    {},
    async () => {
      const wt = requireRegistered()
      if (typeof wt !== 'string') return wt
      const result = await handlers.get_my_tasks({ worktree_id: wt })
      return { content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }] }
    }
  )

  server.tool(
    'start_task',
    'Mark a task as In Progress.',
    { task_id: z.string().describe('UUID of the task to start') },
    async ({ task_id }) => {
      const wt = requireRegistered()
      if (typeof wt !== 'string') return wt
      await handlers.start_task({ worktree_id: wt, task_id })
      return { content: [{ type: 'text' as const, text: `Task ${task_id} started.` }] }
    }
  )

  server.tool(
    'complete_task',
    'Mark task as Done, get next task.',
    { task_id: z.string().describe('UUID of the task to complete') },
    async ({ task_id }) => {
      const wt = requireRegistered()
      if (typeof wt !== 'string') return wt
      const result = await handlers.complete_task({ worktree_id: wt, task_id })
      return { content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }] }
    }
  )

  server.tool(
    'update_task_status',
    'Move task to a specific column (e.g., review, blocked).',
    {
      task_id: z.string().describe('UUID of the task'),
      status: z.string().describe('Target status: backlog, assigned, in_progress, review, done, blocked'),
    },
    async ({ task_id, status }) => {
      const wt = requireRegistered()
      if (typeof wt !== 'string') return wt
      await handlers.update_task_status({ worktree_id: wt, task_id, status })
      return { content: [{ type: 'text' as const, text: `Task ${task_id} moved to ${status}.` }] }
    }
  )

  server.tool(
    'add_task_note',
    'Append a status note to current task.',
    {
      task_id: z.string().describe('UUID of the task'),
      note: z.string().describe('Status note text'),
    },
    async ({ task_id, note }) => {
      const wt = requireRegistered()
      if (typeof wt !== 'string') return wt
      await handlers.add_task_note({ worktree_id: wt, task_id, note })
      return { content: [{ type: 'text' as const, text: 'Note added.' }] }
    }
  )

  server.tool(
    'attach_document',
    'Read a local file and POST its content to cloglog as a document attachment.',
    {
      task_id: z.string().describe('UUID of the task to attach to'),
      file_path: z.string().describe('Absolute path to the file to attach'),
      type: z.enum(['spec', 'plan', 'design', 'other']).describe('Document type'),
      title: z.string().optional().describe('Document title (defaults to filename)'),
    },
    async ({ task_id, file_path, type, title }) => {
      const wt = requireRegistered()
      if (typeof wt !== 'string') return wt
      const fs = await import('node:fs/promises')
      const path = await import('node:path')
      const content = await fs.readFile(file_path, 'utf-8')
      const docTitle = title ?? path.basename(file_path)
      await handlers.attach_document({
        worktree_id: wt,
        task_id,
        type,
        title: docTitle,
        content,
        source_path: file_path,
      })
      return { content: [{ type: 'text' as const, text: `Document "${docTitle}" attached.` }] }
    }
  )

  // ── Board management ──────────────────────────────────

  server.tool(
    'create_tasks',
    'Create epics/features/tasks on the board from a structured breakdown.',
    {
      project_id: z.string().describe('UUID of the project'),
      epics: z.array(z.object({
        title: z.string(),
        features: z.array(z.object({
          title: z.string(),
          tasks: z.array(z.object({
            title: z.string(),
            description: z.string().optional(),
          })).optional(),
        })).optional(),
      })).describe('Structured breakdown'),
    },
    async ({ project_id, epics }) => {
      const result = await handlers.create_tasks({ project_id, epics })
      return { content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }] }
    }
  )

  server.tool(
    'create_epic',
    'Create a new epic in the project.',
    {
      title: z.string().describe('Epic title'),
      description: z.string().optional().describe('Epic description'),
      bounded_context: z.string().optional().describe('DDD bounded context name'),
    },
    async ({ title, description, bounded_context }) => {
      const pid = requireProject()
      if (typeof pid !== 'string') return pid
      const result = await handlers.create_epic({ project_id: pid, title, description, bounded_context })
      return { content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }] }
    }
  )

  server.tool(
    'list_epics',
    'List all epics in the project.',
    {},
    async () => {
      const pid = requireProject()
      if (typeof pid !== 'string') return pid
      const result = await handlers.list_epics({ project_id: pid })
      return { content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }] }
    }
  )

  server.tool(
    'create_feature',
    'Create a new feature under an existing epic.',
    {
      epic_id: z.string().describe('UUID of the parent epic'),
      title: z.string().describe('Feature title'),
      description: z.string().optional().describe('Feature description'),
    },
    async ({ epic_id, title, description }) => {
      const pid = requireProject()
      if (typeof pid !== 'string') return pid
      const result = await handlers.create_feature({ project_id: pid, epic_id, title, description })
      return { content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }] }
    }
  )

  server.tool(
    'list_features',
    'List features in an epic.',
    {
      epic_id: z.string().describe('UUID of the epic'),
    },
    async ({ epic_id }) => {
      const pid = requireProject()
      if (typeof pid !== 'string') return pid
      const result = await handlers.list_features({ project_id: pid, epic_id })
      return { content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }] }
    }
  )

  server.tool(
    'create_task',
    'Create a single task in a feature.',
    {
      feature_id: z.string().describe('UUID of the parent feature'),
      title: z.string().describe('Task title'),
      description: z.string().optional().describe('Task description'),
      priority: z.enum(['normal', 'expedite']).optional().describe('Task priority (default: normal)'),
    },
    async ({ feature_id, title, description, priority }) => {
      const pid = requireProject()
      if (typeof pid !== 'string') return pid
      const result = await handlers.create_task({ project_id: pid, feature_id, title, description, priority })
      return { content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }] }
    }
  )

  server.tool(
    'get_backlog',
    'Get the full epic > feature > task hierarchy for the project.',
    {},
    async () => {
      const pid = requireProject()
      if (typeof pid !== 'string') return pid
      const result = await handlers.get_backlog({ project_id: pid })
      return { content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }] }
    }
  )

  server.tool(
    'get_board',
    'Get the board state showing tasks organized by column (backlog, assigned, in_progress, review, done, blocked).',
    {},
    async () => {
      const pid = requireProject()
      if (typeof pid !== 'string') return pid
      const result = await handlers.get_board({ project_id: pid })
      return { content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }] }
    }
  )

  server.tool(
    'update_task',
    'Edit a task (title, description, or priority).',
    {
      task_id: z.string().describe('UUID of the task'),
      title: z.string().optional().describe('New title'),
      description: z.string().optional().describe('New description'),
      priority: z.enum(['normal', 'expedite']).optional().describe('New priority'),
    },
    async ({ task_id, title, description, priority }) => {
      const result = await handlers.update_task({ task_id, title, description, priority })
      return { content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }] }
    }
  )

  server.tool(
    'delete_task',
    'Delete a task from the board.',
    {
      task_id: z.string().describe('UUID of the task to delete'),
    },
    async ({ task_id }) => {
      await handlers.delete_task({ task_id })
      return { content: [{ type: 'text' as const, text: `Task ${task_id} deleted.` }] }
    }
  )

  return server
}
