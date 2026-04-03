export interface Project {
  id: string
  name: string
  description: string
  repo_url: string
  status: string
  created_at: string
}

export interface ProjectWithKey extends Project {
  api_key: string
}

export interface Epic {
  id: string
  project_id: string
  title: string
  description: string
  bounded_context: string
  status: string
  position: number
  created_at: string
}

export interface Feature {
  id: string
  epic_id: string
  title: string
  description: string
  status: string
  position: number
  created_at: string
}

export interface TaskCard {
  id: string
  feature_id: string
  title: string
  description: string
  status: string
  priority: string
  worktree_id: string | null
  position: number
  created_at: string
  updated_at: string
  epic_title: string
  feature_title: string
}

export interface BoardColumn {
  status: string
  tasks: TaskCard[]
}

export interface BoardResponse {
  project_id: string
  project_name: string
  columns: BoardColumn[]
  total_tasks: number
  done_count: number
}

export interface Worktree {
  id: string
  name: string
  worktree_path: string
  status: string
  current_task_id: string | null
  last_heartbeat: string
}

export interface DocumentSummary {
  id: string
  type: string
  title: string
  created_at: string
}

export interface Document extends DocumentSummary {
  content: string
  source_path: string
  attached_to_type: string
  attached_to_id: string
}

export type SSEEvent = {
  type: 'task_status_changed' | 'worktree_online' | 'worktree_offline' | 'document_attached'
  data: Record<string, string>
}
