import type { CloglogClient } from './client.js'

export interface ToolHandlers {
  register_agent(args: { worktree_path: string }): Promise<unknown>
  get_my_tasks(args: { worktree_id: string }): Promise<unknown>
  start_task(args: { worktree_id: string; task_id: string }): Promise<unknown>
  complete_task(args: { worktree_id: string; task_id: string }): Promise<unknown>
  update_task_status(args: { worktree_id: string; task_id: string; status: string }): Promise<unknown>
  add_task_note(args: { worktree_id: string; task_id: string; note: string }): Promise<unknown>
  attach_document(args: {
    worktree_id: string; task_id: string; type: string;
    title: string; content: string; source_path?: string
  }): Promise<unknown>
  create_tasks(args: {
    project_id: string; epics: Array<{
      title: string; features?: Array<{
        title: string; tasks?: Array<{ title: string; description?: string }>
      }>
    }>
  }): Promise<unknown>
  unregister_agent(args: { worktree_id: string }): Promise<unknown>
}

export function createToolHandlers(client: CloglogClient): ToolHandlers {
  return {
    async register_agent({ worktree_path }) {
      return client.request('POST', '/api/v1/agents/register', { worktree_path })
    },

    async get_my_tasks({ worktree_id }) {
      return client.request('GET', `/api/v1/agents/${worktree_id}/tasks`)
    },

    async start_task({ worktree_id, task_id }) {
      return client.request('POST', `/api/v1/agents/${worktree_id}/start-task`, { task_id })
    },

    async complete_task({ worktree_id, task_id }) {
      return client.request('POST', `/api/v1/agents/${worktree_id}/complete-task`, { task_id })
    },

    async update_task_status({ worktree_id, task_id, status }) {
      return client.request('PATCH', `/api/v1/agents/${worktree_id}/task-status`, { task_id, status })
    },

    async add_task_note({ worktree_id, task_id, note }) {
      return client.request('POST', `/api/v1/agents/${worktree_id}/task-note`, { task_id, note })
    },

    async attach_document({ worktree_id, task_id, type, title, content, source_path }) {
      return client.request('POST', `/api/v1/agents/${worktree_id}/documents`, {
        task_id, type, title, content, source_path: source_path ?? '',
      })
    },

    async create_tasks({ project_id, epics }) {
      return client.request('POST', `/api/v1/projects/${project_id}/import`, { epics })
    },

    async unregister_agent({ worktree_id }) {
      return client.request('POST', `/api/v1/agents/${worktree_id}/unregister`)
    },
  }
}
