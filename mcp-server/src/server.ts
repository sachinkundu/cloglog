import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { z } from 'zod'
import { CloglogClient } from './client.js'
import { HeartbeatTimer } from './heartbeat.js'
import { createToolHandlers } from './tools.js'

export function createServer(client: CloglogClient): McpServer {
  const handlers = createToolHandlers(client)
  let currentWorktreeId: string | null = null
  let currentProjectId: string | null = null
  let shutdownRequested = false
  let pendingMessages: string[] = []
  const heartbeat = new HeartbeatTimer(async () => {
    if (currentWorktreeId) {
      const resp = await client.request('POST', `/api/v1/agents/${currentWorktreeId}/heartbeat`) as Record<string, unknown>
      if (resp?.shutdown_requested) {
        shutdownRequested = true
      }
      // Pick up pending messages from heartbeat response
      const messages = resp?.pending_messages as string[] | undefined
      if (messages && messages.length > 0) {
        pendingMessages.push(...messages)
      }
    }
  })

  /** Drain pending messages and return them as a suffix for tool responses */
  function drainMessages(): string {
    if (pendingMessages.length === 0) return ''
    const msgs = pendingMessages.splice(0, pendingMessages.length)
    return '\n\n📨 MESSAGES:\n' + msgs.map(m => `- ${m}`).join('\n')
  }

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
      let text = JSON.stringify(result, null, 2)
      if (shutdownRequested) {
        text += '\n\n⚠️ SHUTDOWN REQUESTED: The master agent has requested this worktree to shut down. Finish your current work, generate shutdown artifacts (work-log.md and learnings.md in shutdown-artifacts/), call unregister_agent, and exit.'
      }
      text += drainMessages()
      return { content: [{ type: 'text' as const, text }] }
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
      let text = `Task ${task_id} started.`
      text += drainMessages()
      return { content: [{ type: 'text' as const, text }] }
    }
  )

  server.tool(
    'complete_task',
    'BLOCKED: Agents cannot mark tasks done. Move to review and wait for the user to drag the card to done on the board.',
    {
      task_id: z.string().describe('UUID of the task to complete'),
      pr_url: z.string().optional().describe('GitHub PR URL (required for spec/impl tasks)'),
    },
    async ({ task_id, pr_url }) => {
      const wt = requireRegistered()
      if (typeof wt !== 'string') return wt
      const result = await handlers.complete_task({ worktree_id: wt, task_id, pr_url })
      let text = JSON.stringify(result, null, 2)
      if (shutdownRequested) {
        text += '\n\n⚠️ SHUTDOWN REQUESTED: The master agent has requested this worktree to shut down. Finish your current work, generate shutdown artifacts (work-log.md and learnings.md in shutdown-artifacts/), call unregister_agent, and exit.'
      }
      text += drainMessages()
      return { content: [{ type: 'text' as const, text }] }
    }
  )

  server.tool(
    'update_task_status',
    'Move task to a specific column. Agents can move to review (with pr_url for spec/impl) but CANNOT move to done — only the user can.',
    {
      task_id: z.string().describe('UUID of the task'),
      status: z.string().describe('Target status: backlog, in_progress, review, done'),
      pr_url: z.string().optional().describe('GitHub PR URL (required when moving spec/impl tasks to review)'),
    },
    async ({ task_id, status, pr_url }) => {
      const wt = requireRegistered()
      if (typeof wt !== 'string') return wt
      await handlers.update_task_status({ worktree_id: wt, task_id, status, pr_url })
      let text = `Task ${task_id} moved to ${status}.`
      text += drainMessages()
      return { content: [{ type: 'text' as const, text }] }
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
    'Read a local file and attach it as a document to an epic, feature, or task.',
    {
      entity_type: z.enum(['epic', 'feature', 'task']).describe('Type of entity to attach to'),
      entity_id: z.string().describe('UUID of the epic, feature, or task'),
      file_path: z.string().describe('Absolute path to the file to attach'),
      type: z.enum(['spec', 'plan', 'design', 'other']).describe('Document type'),
      title: z.string().optional().describe('Document title (defaults to filename)'),
    },
    async ({ entity_type, entity_id, file_path, type, title }) => {
      requireRegistered()
      const fs = await import('node:fs/promises')
      const path = await import('node:path')
      const content = await fs.readFile(file_path, 'utf-8')
      const docTitle = title ?? path.basename(file_path)
      await handlers.attach_document({
        entity_type,
        entity_id,
        type,
        title: docTitle,
        content,
        source_path: file_path,
      })
      return { content: [{ type: 'text' as const, text: `Document "${docTitle}" attached to ${entity_type} ${entity_id}.` }] }
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
      task_type: z.enum(['spec', 'plan', 'impl', 'task']).optional().describe('Task type for pipeline ordering. spec → plan → impl. Default: task (no pipeline deps)'),
    },
    async ({ feature_id, title, description, priority, task_type }) => {
      const pid = requireProject()
      if (typeof pid !== 'string') return pid
      const result = await handlers.create_task({ project_id: pid, feature_id, title, description, priority, task_type })
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
    'Get the board state showing tasks organized by column. Supports filtering to reduce response size.',
    {
      epic_id: z.string().optional().describe('Filter to tasks under this epic UUID'),
      exclude_done: z.boolean().optional().describe('Exclude done tasks (default: false)'),
    },
    async ({ epic_id, exclude_done }) => {
      const pid = requireProject()
      if (typeof pid !== 'string') return pid
      const result = await handlers.get_board({ project_id: pid, epic_id, exclude_done })
      return { content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }] }
    }
  )

  server.tool(
    'get_active_tasks',
    'Get a compact list of non-done, non-archived tasks. Much smaller than get_board — use this when you only need task IDs, statuses, and titles.',
    {},
    async () => {
      const pid = requireProject()
      if (typeof pid !== 'string') return pid
      const result = await handlers.get_active_tasks({ project_id: pid })
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

  server.tool(
    'send_agent_message',
    'Send a message to another agent by worktree ID. The message is delivered on the target agent\'s next heartbeat (within ~60s) via tool response piggyback.',
    {
      worktree_id: z.string().describe('UUID of the target agent worktree'),
      message: z.string().describe('Message to deliver'),
    },
    async ({ worktree_id, message }) => {
      await handlers.send_agent_message({ worktree_id, message, sender: currentWorktreeId ?? 'main-agent' })
      return { content: [{ type: 'text' as const, text: `Message queued for delivery to agent ${worktree_id}.` }] }
    }
  )

  return server
}
