import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { z } from 'zod'
import { CloglogClient } from './client.js'
import { HeartbeatTimer } from './heartbeat.js'
import { createToolHandlers } from './tools.js'

export function createServer(client: CloglogClient): McpServer {
  const handlers = createToolHandlers(client)
  let currentWorktreeId: string | null = null
  const heartbeat = new HeartbeatTimer(async () => {
    if (currentWorktreeId) {
      await client.request('POST', `/api/v1/agents/${currentWorktreeId}/heartbeat`)
    }
  })

  const server = new McpServer({
    name: 'cloglog-mcp',
    version: '0.1.0',
  })

  server.tool(
    'register_agent',
    'Register this worktree with cloglog. Called at session start. Returns current task if resuming.',
    { worktree_path: z.string().describe('Absolute path to the git worktree') },
    async ({ worktree_path }) => {
      const result = await handlers.register_agent({ worktree_path }) as Record<string, unknown>
      currentWorktreeId = result.worktree_id as string
      heartbeat.start()
      return { content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }] }
    }
  )

  server.tool(
    'get_my_tasks',
    'Get ordered list of tasks assigned to this worktree.',
    {},
    async () => {
      if (!currentWorktreeId) {
        return { content: [{ type: 'text' as const, text: 'Error: Not registered. Call register_agent first.' }] }
      }
      const result = await handlers.get_my_tasks({ worktree_id: currentWorktreeId })
      return { content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }] }
    }
  )

  server.tool(
    'start_task',
    'Mark a task as In Progress.',
    { task_id: z.string().describe('UUID of the task to start') },
    async ({ task_id }) => {
      if (!currentWorktreeId) {
        return { content: [{ type: 'text' as const, text: 'Error: Not registered.' }] }
      }
      await handlers.start_task({ worktree_id: currentWorktreeId, task_id })
      return { content: [{ type: 'text' as const, text: `Task ${task_id} started.` }] }
    }
  )

  server.tool(
    'complete_task',
    'Mark task as Done, get next task.',
    { task_id: z.string().describe('UUID of the task to complete') },
    async ({ task_id }) => {
      if (!currentWorktreeId) {
        return { content: [{ type: 'text' as const, text: 'Error: Not registered.' }] }
      }
      const result = await handlers.complete_task({ worktree_id: currentWorktreeId, task_id })
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
      if (!currentWorktreeId) {
        return { content: [{ type: 'text' as const, text: 'Error: Not registered.' }] }
      }
      await handlers.update_task_status({ worktree_id: currentWorktreeId, task_id, status })
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
      if (!currentWorktreeId) {
        return { content: [{ type: 'text' as const, text: 'Error: Not registered.' }] }
      }
      await handlers.add_task_note({ worktree_id: currentWorktreeId, task_id, note })
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
      if (!currentWorktreeId) {
        return { content: [{ type: 'text' as const, text: 'Error: Not registered.' }] }
      }
      const fs = await import('node:fs/promises')
      const path = await import('node:path')
      const content = await fs.readFile(file_path, 'utf-8')
      const docTitle = title ?? path.basename(file_path)
      await handlers.attach_document({
        worktree_id: currentWorktreeId,
        task_id,
        type,
        title: docTitle,
        content,
        source_path: file_path,
      })
      return { content: [{ type: 'text' as const, text: `Document "${docTitle}" attached.` }] }
    }
  )

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
    'unregister_agent',
    'Sign off cleanly when session ends.',
    {},
    async () => {
      if (!currentWorktreeId) {
        return { content: [{ type: 'text' as const, text: 'Error: Not registered.' }] }
      }
      heartbeat.stop()
      await handlers.unregister_agent({ worktree_id: currentWorktreeId })
      const id = currentWorktreeId
      currentWorktreeId = null
      return { content: [{ type: 'text' as const, text: `Unregistered ${id}.` }] }
    }
  )

  return server
}
