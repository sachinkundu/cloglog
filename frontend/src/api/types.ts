// Re-export generated API types as app-friendly names.
// DO NOT hand-write API response types here — they come from the OpenAPI contract.
// Only add frontend-only types (not API responses) in this file.
// Regenerate with: ./scripts/generate-contract-types.sh docs/contracts/baseline.openapi.yaml

import type { components } from './generated-types'

// API response types — derived from OpenAPI contract
export type Project = components['schemas']['ProjectResponse']
export type ProjectWithKey = components['schemas']['ProjectWithKey']
export type Epic = components['schemas']['EpicResponse']
export type Feature = components['schemas']['FeatureResponse']
export type TaskCard = components['schemas']['TaskCard']
export type Worktree = components['schemas']['WorktreeResponse']
export type DocumentSummary = Pick<
  components['schemas']['DocumentResponse'],
  'id' | 'doc_type' | 'title' | 'created_at'
>
export type Document = components['schemas']['DocumentResponse']

// Backlog tree types
export type BacklogEpic = components['schemas']['BacklogEpic']
export type BacklogFeature = components['schemas']['BacklogFeature']
export type BacklogTask = components['schemas']['BacklogTask']
export type TaskCounts = components['schemas']['TaskCounts']

// Task notes (not yet in OpenAPI contract)
export interface TaskNote {
  id: string
  task_id: string
  note: string
  created_at: string
}

// Notifications (not yet in OpenAPI contract)
// Using AppNotification to avoid collision with browser's built-in Notification API
export interface AppNotification {
  id: string
  project_id: string
  task_id: string
  task_title: string
  task_number: number
  read: boolean
  created_at: string
}

// Frontend-only types (not from API)
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

export type SSEEvent = {
  type:
    | 'task_status_changed'
    | 'worktree_online'
    | 'worktree_offline'
    | 'document_attached'
    | 'epic_created'
    | 'epic_deleted'
    | 'feature_created'
    | 'feature_deleted'
    | 'task_created'
    | 'task_deleted'
    | 'task_note_added'
    | 'bulk_import'
    | 'notification_created'
  data: Record<string, string>
}
