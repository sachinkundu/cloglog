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
  type: 'task_status_changed' | 'worktree_online' | 'worktree_offline' | 'document_attached'
  data: Record<string, string>
}
