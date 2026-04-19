import { execFileSync } from 'node:child_process'

import type { CloglogClient } from './client.js'

/**
 * Resolve the current branch at ``worktree_path`` via ``git symbolic-ref``.
 *
 * Runs inside the agent-vm (where cloglog-mcp lives — see
 * ``docs/ddd-context-map.md``). The backend runs on the host and cannot see
 * VM-local paths, so we derive the branch name here and pass it over the wire.
 *
 * Returns ``""`` when the path is missing, is not a git repo, or is in
 * detached-HEAD state (``symbolic-ref`` exits non-zero). The backend's
 * webhook resolver short-circuits on empty branch names, so returning ``""``
 * is a safe fallback.
 */
export function deriveBranchName(worktreePath: string): string {
  try {
    return execFileSync(
      'git',
      ['-C', worktreePath, 'symbolic-ref', '--short', 'HEAD'],
      { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] },
    ).trim()
  } catch {
    return ''
  }
}

export interface ToolHandlers {
  register_agent(args: { worktree_path: string }): Promise<unknown>
  get_my_tasks(args: { worktree_id: string }): Promise<unknown>
  start_task(args: { worktree_id: string; task_id: string }): Promise<unknown>
  complete_task(args: { worktree_id: string; task_id: string; pr_url?: string }): Promise<unknown>
  update_task_status(args: { worktree_id: string; task_id: string; status: string; pr_url?: string; skip_pr?: boolean }): Promise<unknown>
  add_task_note(args: { worktree_id: string; task_id: string; note: string }): Promise<unknown>
  attach_document(args: {
    entity_type: string; entity_id: string; type: string;
    title: string; content: string; source_path?: string
  }): Promise<unknown>
  create_tasks(args: {
    project_id: string; epics: Array<{
      title: string; features?: Array<{
        title: string; tasks?: Array<{ title: string; description?: string }>
      }>
    }>
  }): Promise<unknown>
  assign_task(args: { worktree_id: string; task_id: string }): Promise<unknown>
  unregister_agent(args: { worktree_id: string }): Promise<unknown>
  report_artifact(args: { worktree_id: string; task_id: string; artifact_path: string }): Promise<unknown>
  mark_pr_merged(args: { worktree_id: string; task_id: string }): Promise<unknown>

  // New tools for API parity
  get_project(args: Record<string, never>): Promise<unknown>
  create_epic(args: { project_id: string; title: string; description?: string; bounded_context?: string }): Promise<unknown>
  list_epics(args: { project_id: string }): Promise<unknown>
  create_feature(args: { project_id: string; epic_id: string; title: string; description?: string }): Promise<unknown>
  list_features(args: { project_id: string; epic_id: string }): Promise<unknown>
  create_task(args: { project_id: string; feature_id: string; title: string; description?: string; priority?: string; task_type?: string }): Promise<unknown>
  get_backlog(args: { project_id: string }): Promise<unknown>
  get_board(args: { project_id: string; epic_id?: string; exclude_done?: boolean }): Promise<unknown>
  get_active_tasks(args: { project_id: string }): Promise<unknown>
  update_epic(args: { epic_id: string; title?: string; description?: string; bounded_context?: string; status?: string }): Promise<unknown>
  delete_epic(args: { epic_id: string }): Promise<unknown>
  update_feature(args: { feature_id: string; title?: string; description?: string; status?: string }): Promise<unknown>
  delete_feature(args: { feature_id: string }): Promise<unknown>
  update_task(args: { task_id: string; title?: string; description?: string; priority?: string }): Promise<unknown>
  delete_task(args: { task_id: string }): Promise<unknown>
  add_dependency(args: { feature_id: string; depends_on_id: string }): Promise<unknown>
  remove_dependency(args: { feature_id: string; depends_on_id: string }): Promise<unknown>
  add_task_dependency(args: { task_id: string; depends_on_id: string }): Promise<unknown>
  remove_task_dependency(args: { task_id: string; depends_on_id: string }): Promise<unknown>
}

export function createToolHandlers(client: CloglogClient): ToolHandlers {
  return {
    async register_agent({ worktree_path }) {
      // Derive branch_name here (inside the VM) because the backend runs on
      // the host and cannot reach VM-local paths. The backend stores whatever
      // we send; its resolver guards handle any residual empty values safely.
      const branch_name = deriveBranchName(worktree_path)
      return client.request('POST', '/api/v1/agents/register', {
        worktree_path,
        branch_name,
      })
    },

    async get_my_tasks({ worktree_id }) {
      return client.request('GET', `/api/v1/agents/${worktree_id}/tasks`)
    },

    async start_task({ worktree_id, task_id }) {
      return client.request('POST', `/api/v1/agents/${worktree_id}/start-task`, { task_id })
    },

    async complete_task({ worktree_id, task_id, pr_url }) {
      return client.request('POST', `/api/v1/agents/${worktree_id}/complete-task`, {
        task_id,
        ...(pr_url ? { pr_url } : {}),
      })
    },

    async update_task_status({ worktree_id, task_id, status, pr_url, skip_pr }) {
      return client.request('PATCH', `/api/v1/agents/${worktree_id}/task-status`, {
        task_id,
        status,
        ...(pr_url ? { pr_url } : {}),
        ...(skip_pr ? { skip_pr } : {}),
      })
    },

    async add_task_note({ worktree_id, task_id, note }) {
      return client.request('POST', `/api/v1/agents/${worktree_id}/task-note`, { task_id, note })
    },

    async attach_document({ entity_type, entity_id, type, title, content, source_path }) {
      return client.request('POST', '/api/v1/documents', {
        attached_to_type: entity_type,
        attached_to_id: entity_id,
        doc_type: type,
        title,
        content,
        source_path: source_path ?? '',
      })
    },

    async create_tasks({ project_id, epics }) {
      return client.request('POST', `/api/v1/projects/${project_id}/import`, { epics })
    },

    async assign_task({ worktree_id, task_id }) {
      return client.request('PATCH', `/api/v1/agents/${worktree_id}/assign-task`, { task_id })
    },

    async unregister_agent({ worktree_id }) {
      return client.request('POST', `/api/v1/agents/${worktree_id}/unregister`)
    },

    async report_artifact({ worktree_id, task_id, artifact_path }) {
      return client.request('POST', `/api/v1/agents/${worktree_id}/report-artifact`, {
        task_id,
        artifact_path,
      })
    },

    async mark_pr_merged({ worktree_id, task_id }) {
      return client.request('POST', `/api/v1/agents/${worktree_id}/mark-pr-merged`, { task_id })
    },

    // New tools for API parity

    async get_project() {
      return client.request('GET', '/api/v1/gateway/me')
    },

    async create_epic({ project_id, title, description, bounded_context }) {
      return client.request('POST', `/api/v1/projects/${project_id}/epics`, {
        title,
        description: description ?? '',
        bounded_context: bounded_context ?? '',
      })
    },

    async list_epics({ project_id }) {
      return client.request('GET', `/api/v1/projects/${project_id}/epics`)
    },

    async create_feature({ project_id, epic_id, title, description }) {
      return client.request('POST', `/api/v1/projects/${project_id}/epics/${epic_id}/features`, {
        title,
        description: description ?? '',
      })
    },

    async list_features({ project_id, epic_id }) {
      return client.request('GET', `/api/v1/projects/${project_id}/epics/${epic_id}/features`)
    },

    async create_task({ project_id, feature_id, title, description, priority, task_type }) {
      return client.request('POST', `/api/v1/projects/${project_id}/features/${feature_id}/tasks`, {
        title,
        description: description ?? '',
        priority: priority ?? 'normal',
        task_type: task_type ?? 'task',
      })
    },

    async get_backlog({ project_id }) {
      return client.request('GET', `/api/v1/projects/${project_id}/backlog`)
    },

    async get_board({ project_id, epic_id, exclude_done }) {
      const params = new URLSearchParams()
      if (epic_id) params.set('epic_id', epic_id)
      if (exclude_done) params.set('exclude_done', 'true')
      const qs = params.toString()
      return client.request('GET', `/api/v1/projects/${project_id}/board${qs ? `?${qs}` : ''}`)
    },

    async get_active_tasks({ project_id }) {
      return client.request('GET', `/api/v1/projects/${project_id}/active-tasks`)
    },

    async update_epic({ epic_id, title, description, bounded_context, status }) {
      const fields: Record<string, string> = {}
      if (title !== undefined) fields.title = title
      if (description !== undefined) fields.description = description
      if (bounded_context !== undefined) fields.bounded_context = bounded_context
      if (status !== undefined) fields.status = status
      return client.request('PATCH', `/api/v1/epics/${epic_id}`, fields)
    },

    async delete_epic({ epic_id }) {
      return client.request('DELETE', `/api/v1/epics/${epic_id}`)
    },

    async update_feature({ feature_id, title, description, status }) {
      const fields: Record<string, string> = {}
      if (title !== undefined) fields.title = title
      if (description !== undefined) fields.description = description
      if (status !== undefined) fields.status = status
      return client.request('PATCH', `/api/v1/features/${feature_id}`, fields)
    },

    async delete_feature({ feature_id }) {
      return client.request('DELETE', `/api/v1/features/${feature_id}`)
    },

    async update_task({ task_id, title, description, priority }) {
      const fields: Record<string, string> = {}
      if (title !== undefined) fields.title = title
      if (description !== undefined) fields.description = description
      if (priority !== undefined) fields.priority = priority
      return client.request('PATCH', `/api/v1/tasks/${task_id}`, fields)
    },

    async delete_task({ task_id }) {
      return client.request('DELETE', `/api/v1/tasks/${task_id}`)
    },

    async add_dependency({ feature_id, depends_on_id }) {
      return client.request('POST', `/api/v1/features/${feature_id}/dependencies`, { depends_on_id })
    },

    async remove_dependency({ feature_id, depends_on_id }) {
      return client.request('DELETE', `/api/v1/features/${feature_id}/dependencies/${depends_on_id}`)
    },

    async add_task_dependency({ task_id, depends_on_id }) {
      return client.request('POST', `/api/v1/tasks/${task_id}/dependencies`, { depends_on_id })
    },

    async remove_task_dependency({ task_id, depends_on_id }) {
      return client.request('DELETE', `/api/v1/tasks/${task_id}/dependencies/${depends_on_id}`)
    },
  }
}
