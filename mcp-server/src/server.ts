import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { z } from 'zod'
import { CloglogClient } from './client.js'
import { CloglogApiError } from './errors.js'
import { HeartbeatTimer } from './heartbeat.js'
import { createToolHandlers } from './tools.js'

/**
 * Render a structured blocker (as emitted by the F-11 ``task_blocked``
 * 409 payload) as a single readable line.
 */
function formatBlocker(b: Record<string, unknown>): string {
  const kind = b.kind
  if (kind === 'feature') {
    const tasks = (b.incomplete_task_numbers as number[] | undefined) ?? []
    const joined = tasks.map((n) => `T-${n}`).join(', ')
    return `  • Feature F-${b.feature_number} "${b.feature_title}" — incomplete tasks: ${joined || '(none)'}`
  }
  if (kind === 'task') {
    return `  • Task T-${b.task_number} "${b.task_title}" (${b.status})`
  }
  if (kind === 'pipeline') {
    return `  • Pipeline: ${b.predecessor_task_type} task T-${b.task_number} "${b.task_title}" (${b.status}, reason=${b.reason})`
  }
  return `  • ${JSON.stringify(b)}`
}

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

  /** Wrap a tool handler to catch API errors and return them as isError responses */
  function wrapHandler<T extends Record<string, unknown>>(
    fn: (args: T) => Promise<{ content: Array<{ type: 'text'; text: string }>; isError?: boolean }>
  ) {
    return async (args: T) => {
      try {
        return await fn(args)
      } catch (err: unknown) {
        // Structured "task_blocked" 409 — render blockers as readable text
        // so the agent can see *why* the guard rejected rather than a
        // JSON blob or a flattened string.
        if (err instanceof CloglogApiError && err.code === 'task_blocked') {
          const d = err.structured ?? {}
          const lines: string[] = []
          lines.push(`⛔ ${d.message ?? 'Task is blocked.'}`)
          for (const b of d.blockers ?? []) {
            lines.push(formatBlocker(b))
          }
          return { content: [{ type: 'text' as const, text: lines.join('\n') }], isError: true }
        }
        const message = err instanceof Error ? err.message : String(err)
        return { content: [{ type: 'text' as const, text: `⛔ ${message}` }], isError: true }
      }
    }
  }

  // ── Agent lifecycle ───────────────────────────────────

  server.tool(
    'register_agent',
    'Register this worktree with cloglog. Called at session start. Returns current task if resuming.',
    { worktree_path: z.string().describe('Absolute path to the git worktree') },
    async ({ worktree_path }) => {
      const result = await handlers.register_agent({ worktree_path }) as Record<string, unknown>
      currentWorktreeId = result.worktree_id as string
      currentProjectId = result.project_id as string
      // Store agent token for subsequent agent-scoped requests
      const agentToken = result.agent_token as string | undefined
      if (agentToken) {
        client.setAgentToken(agentToken)
      }
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
      client.clearAgentToken()
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
      const text = JSON.stringify(result, null, 2)
      return { content: [{ type: 'text' as const, text }] }
    }
  )

  server.tool(
    'start_task',
    'Mark a task as In Progress. Guards: only one active task per agent, and pipeline ordering enforced (spec before plan, plan before impl).',
    { task_id: z.string().describe('UUID of the task to start') },
    wrapHandler(async ({ task_id }: { task_id: string }) => {
      const wt = requireRegistered()
      if (typeof wt !== 'string') return wt
      await handlers.start_task({ worktree_id: wt, task_id })
      const text = `Task ${task_id} started.`
      return { content: [{ type: 'text' as const, text }] }
    })
  )

  server.tool(
    'assign_task',
    'Assign a task to a running agent by worktree ID. Sets worktree_id on the task without changing status, so get_my_tasks returns it. Also sends a message to the target agent.',
    {
      worktree_id: z.string().describe('UUID of the target agent worktree'),
      task_id: z.string().describe('UUID of the task to assign'),
    },
    async ({ worktree_id, task_id }) => {
      const result = await handlers.assign_task({ worktree_id, task_id })
      const text = JSON.stringify(result, null, 2)
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
    wrapHandler(async ({ task_id, pr_url }: { task_id: string; pr_url?: string }) => {
      const wt = requireRegistered()
      if (typeof wt !== 'string') return wt
      const result = await handlers.complete_task({ worktree_id: wt, task_id, pr_url })
      const text = JSON.stringify(result, null, 2)
      return { content: [{ type: 'text' as const, text }] }
    })
  )

  server.tool(
    'update_task_status',
    'Move task to a specific column. Agents can move to review (pr_url REQUIRED unless skip_pr=true for docs/research tasks) but CANNOT move to done — only the user can.',
    {
      task_id: z.string().describe('UUID of the task'),
      status: z.string().describe('Target status: backlog, in_progress, review, done'),
      pr_url: z.string().optional().describe('GitHub PR URL (REQUIRED when moving to review, unless skip_pr is true)'),
      skip_pr: z.boolean().optional().describe('Skip PR requirement ONLY for tasks with zero source code changes (no .py, .ts, .tsx, .js files modified). Valid for: research, prototypes, documentation-only tasks. Any change to src/, tests/, frontend/src/, or mcp-server/src/ MUST have a PR.'),
    },
    wrapHandler(async ({ task_id, status, pr_url, skip_pr }: { task_id: string; status: string; pr_url?: string; skip_pr?: boolean }) => {
      const wt = requireRegistered()
      if (typeof wt !== 'string') return wt
      await handlers.update_task_status({ worktree_id: wt, task_id, status, pr_url, skip_pr })
      let text = `Task ${task_id} moved to ${status}.`
      if (status === 'review' && pr_url) {
        const prNum = pr_url.match(/\/pull\/(\d+)/)?.[1] ?? '???'
        text += `\n\nCRITICAL — PR #${prNum} is now tracked via GitHub webhooks. Do NOT start a /loop polling cycle. Keep your inbox monitor running; events arrive as JSON lines appended to your inbox file:\n\n- {"type":"review_submitted",...}  → reviewer submitted a review. Move task back to in_progress, address the feedback, push a fix, move back to review.\n- {"type":"review_comment",...}    → reviewer posted a standalone inline diff comment (path+line in payload). Same flow as review_submitted.\n- {"type":"issue_comment",...}     → reviewer posted an issue-style PR comment. Read the body; if it requires code changes, apply the same in_progress → fix → review flow. Otherwise reply and stay in review.\n- {"type":"ci_failed",...}         → a CI check terminated with non-success. Use the github-bot skill to read the failed logs and push a fix. (Note: conclusion=null means still pending — verify with gh pr checks.)\n- {"type":"pr_merged","pr_number":${prNum},...}  → PR merged. Call mark_pr_merged with your active task_id (the event does NOT include task_id), then call report_artifact (for spec/plan tasks), then call get_my_tasks and start the next task.\n\nSee the github-bot skill's "PR Event Inbox" section for payload details. Webhook delivery is sub-second — no polling needed. Continue with other work or wait for the next inbox event.`
      }
      return { content: [{ type: 'text' as const, text }] }
    })
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

  server.tool(
    'report_artifact',
    'Report the artifact path for a spec or plan task after its PR merges. Required state machine step — pipeline blocks downstream tasks until artifact is attached.',
    {
      worktree_id: z.string().describe('UUID of the worktree'),
      task_id: z.string().describe('UUID of the spec or plan task'),
      artifact_path: z.string().describe('Repo-relative path to the artifact file (e.g. docs/specs/F-1-spec.md)'),
    },
    async ({ worktree_id, task_id, artifact_path }) => {
      requireRegistered()
      await handlers.report_artifact({ worktree_id, task_id, artifact_path })
      return { content: [{ type: 'text' as const, text: `Artifact reported for task ${task_id}: ${artifact_path}` }] }
    }
  )

  server.tool(
    'create_close_off_task',
    'Find-or-create the paired close-off task for a newly created worktree (T-246). Called by .cloglog/on-worktree-create.sh at worktree bootstrap and by the launch skill so every worktree lands a first-class teardown card on the board. Idempotent on worktree_path — re-running for the same worktree returns the existing task with created=false.',
    {
      worktree_path: z.string().describe('Absolute path of the newly created worktree this close-off task is paired with'),
      worktree_name: z.string().describe('Human-readable worktree name (e.g. wt-f42-foo) shown on the board card'),
    },
    wrapHandler(async ({ worktree_path, worktree_name }: { worktree_path: string; worktree_name: string }) => {
      const result = await handlers.create_close_off_task({ worktree_path, worktree_name })
      return { content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }] }
    })
  )

  server.tool(
    'mark_pr_merged',
    'Set pr_merged=True on a task. Call this after receiving a pr_merged inbox event (idempotent — the webhook consumer also flips this flag), or as a fallback when the webhook does not fire. This allows start_task to proceed for the next task.',
    {
      worktree_id: z.string().describe('UUID of the worktree'),
      task_id: z.string().describe('UUID of the task whose PR was merged'),
    },
    async ({ worktree_id, task_id }) => {
      requireRegistered()
      const result = await handlers.mark_pr_merged({ worktree_id, task_id })
      return { content: [{ type: 'text' as const, text: `PR marked as merged: ${JSON.stringify(result)}` }] }
    }
  )

  // ── Supervisor shutdown (F-48) ────────────────────────

  server.tool(
    'request_shutdown',
    'Tier-1 shutdown: ask a worktree agent to shut down gracefully. Writes a "shutdown" JSON line to <worktree>/.cloglog/inbox so the agent Monitor delivers it instantly. Idempotent — a repeat call re-delivers the signal but does not change state. Returns {"shutdown_requested": true} on success. This is the FIRST lever the supervisor should pull; only escalate to force_unregister if the agent is wedged and never completes.',
    {
      worktree_id: z.string().describe('UUID of the worktree to shut down'),
    },
    wrapHandler(async ({ worktree_id }: { worktree_id: string }) => {
      const result = await handlers.request_shutdown({ worktree_id })
      return { content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }] }
    })
  )

  server.tool(
    'force_unregister',
    'TIER-2 fallback ONLY — call request_shutdown first and give the agent time to exit gracefully. Use force_unregister only when that times out. Ends the worktree session, deletes the worktree row, and emits WORKTREE_OFFLINE(reason=force_unregistered). Idempotent: if the worktree is already gone, returns {"already_unregistered": true} without re-emitting the event. Agent tokens are refused; this must be invoked by the supervisor.',
    {
      worktree_id: z.string().describe('UUID of the wedged worktree to forcibly remove'),
    },
    wrapHandler(async ({ worktree_id }: { worktree_id: string }) => {
      const result = await handlers.force_unregister({ worktree_id })
      return { content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }] }
    })
  )

  server.tool(
    'list_worktrees',
    'List all worktrees for the current project with their id, name, worktree_path, branch_name, status, current_task_id, last_heartbeat, and created_at. Supervisor uses this to map filesystem worktree paths (from `git worktree list`) back to worktree_ids for cooperative shutdown (close-wave / reconcile), to detect wedged agents (status=online + stale heartbeat), and to detect orphaned worktrees (path exists on disk but row has status=offline or is missing). Survives supervisor restarts — does not rely on the ephemeral supervisor inbox.',
    {},
    wrapHandler(async () => {
      const pid = requireProject()
      if (typeof pid !== 'string') return pid
      const result = await handlers.list_worktrees({ project_id: pid })
      return { content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }] }
    })
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
    'update_epic',
    'Update an epic (title, description, bounded_context, or status).',
    {
      epic_id: z.string().describe('UUID of the epic'),
      title: z.string().optional().describe('New title'),
      description: z.string().optional().describe('New description'),
      bounded_context: z.string().optional().describe('New bounded context'),
      status: z.string().optional().describe('New status'),
    },
    async ({ epic_id, title, description, bounded_context, status }) => {
      const result = await handlers.update_epic({ epic_id, title, description, bounded_context, status })
      return { content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }] }
    }
  )

  server.tool(
    'delete_epic',
    'Delete an epic and all its features and tasks.',
    {
      epic_id: z.string().describe('UUID of the epic to delete'),
    },
    async ({ epic_id }) => {
      await handlers.delete_epic({ epic_id })
      return { content: [{ type: 'text' as const, text: `Epic ${epic_id} deleted.` }] }
    }
  )

  server.tool(
    'update_feature',
    'Update a feature (title, description, or status).',
    {
      feature_id: z.string().describe('UUID of the feature'),
      title: z.string().optional().describe('New title'),
      description: z.string().optional().describe('New description'),
      status: z.string().optional().describe('New status'),
    },
    async ({ feature_id, title, description, status }) => {
      const result = await handlers.update_feature({ feature_id, title, description, status })
      return { content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }] }
    }
  )

  server.tool(
    'delete_feature',
    'Delete a feature and all its tasks.',
    {
      feature_id: z.string().describe('UUID of the feature to delete'),
    },
    async ({ feature_id }) => {
      await handlers.delete_feature({ feature_id })
      return { content: [{ type: 'text' as const, text: `Feature ${feature_id} deleted.` }] }
    }
  )

  // ── Feature dependencies ─────────────────────────────

  server.tool(
    'add_dependency',
    'Add a dependency between two features. The feature_id feature will depend on depends_on_id (i.e. depends_on_id must be completed first). Validates both features are in the same project and rejects cycles.',
    {
      feature_id: z.string().describe('UUID of the feature that depends on another'),
      depends_on_id: z.string().describe('UUID of the feature that must be completed first'),
    },
    wrapHandler(async ({ feature_id, depends_on_id }: { feature_id: string; depends_on_id: string }) => {
      await handlers.add_dependency({ feature_id, depends_on_id })
      return { content: [{ type: 'text' as const, text: `Dependency added: feature ${feature_id} now depends on ${depends_on_id}.` }] }
    })
  )

  server.tool(
    'remove_dependency',
    'Remove a dependency between two features.',
    {
      feature_id: z.string().describe('UUID of the feature'),
      depends_on_id: z.string().describe('UUID of the dependency to remove'),
    },
    wrapHandler(async ({ feature_id, depends_on_id }: { feature_id: string; depends_on_id: string }) => {
      await handlers.remove_dependency({ feature_id, depends_on_id })
      return { content: [{ type: 'text' as const, text: `Dependency removed: feature ${feature_id} no longer depends on ${depends_on_id}.` }] }
    })
  )

  // ── Task dependencies (F-11) ─────────────────────────

  server.tool(
    'add_task_dependency',
    'Add a blocked_by edge between two tasks. Task task_id is blocked until depends_on_id is done (or in review with a pr_url). Both tasks must be in the same project; self-loops and cycles are rejected.',
    {
      task_id: z.string().describe('UUID of the task that will be blocked'),
      depends_on_id: z.string().describe('UUID of the task that must complete first'),
    },
    wrapHandler(async ({ task_id, depends_on_id }: { task_id: string; depends_on_id: string }) => {
      await handlers.add_task_dependency({ task_id, depends_on_id })
      return { content: [{ type: 'text' as const, text: `Task dependency added: ${task_id} blocked_by ${depends_on_id}.` }] }
    })
  )

  server.tool(
    'remove_task_dependency',
    'Remove a blocked_by edge between two tasks.',
    {
      task_id: z.string().describe('UUID of the downstream (blocked) task'),
      depends_on_id: z.string().describe('UUID of the upstream dependency to remove'),
    },
    wrapHandler(async ({ task_id, depends_on_id }: { task_id: string; depends_on_id: string }) => {
      await handlers.remove_task_dependency({ task_id, depends_on_id })
      return { content: [{ type: 'text' as const, text: `Task dependency removed: ${task_id} no longer blocked_by ${depends_on_id}.` }] }
    })
  )

  return server
}
