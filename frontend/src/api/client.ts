import type { AppNotification, BacklogEpic, BoardResponse, DependencyGraphResponse, Document, DocumentSummary, Project, SearchResponse, TaskNote, Worktree } from './types'

const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api/v1'

async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!resp.ok) {
    throw new Error(`API error: ${resp.status} ${resp.statusText}`)
  }
  return resp.json()
}

export const api = {
  // Projects
  listProjects: () => fetchJSON<Project[]>('/projects'),
  getProject: (id: string) => fetchJSON<Project>(`/projects/${id}`),

  // Board
  getBoard: (projectId: string) => fetchJSON<BoardResponse>(`/projects/${projectId}/board`),

  // Worktrees
  getWorktrees: (projectId: string) => fetchJSON<Worktree[]>(`/projects/${projectId}/worktrees`),

  // Backlog tree
  getBacklog: (projectId: string) => fetchJSON<BacklogEpic[]>(`/projects/${projectId}/backlog`),

  // Documents
  getTaskDocuments: (taskId: string) => fetchJSON<DocumentSummary[]>(`/tasks/${taskId}/documents`),
  getTaskNotes: (taskId: string) => fetchJSON<TaskNote[]>(`/tasks/${taskId}/notes`),
  getDocument: (id: string) => fetchJSON<Document>(`/documents/${id}`),
  getEpicDocuments: (epicId: string) =>
    fetchJSON<DocumentSummary[]>(`/documents?attached_to_type=epic&attached_to_id=${epicId}`),
  getFeatureDocuments: (featureId: string) =>
    fetchJSON<DocumentSummary[]>(`/documents?attached_to_type=feature&attached_to_id=${featureId}`),

  // Tasks
  archiveTask: (taskId: string) =>
    fetchJSON(`/tasks/${taskId}`, {
      method: 'PATCH',
      body: JSON.stringify({ archived: true }),
    }),

  // Notifications
  getNotifications: (projectId: string) =>
    fetchJSON<AppNotification[]>(`/projects/${projectId}/notifications`),
  markNotificationRead: (notificationId: string) =>
    fetchJSON<AppNotification>(`/notifications/${notificationId}/read`, { method: 'PATCH' }),
  markAllNotificationsRead: (projectId: string) =>
    fetchJSON<{ marked_read: number }>(`/projects/${projectId}/notifications/read-all`, {
      method: 'POST',
    }),
  dismissTaskNotification: (projectId: string, taskId: string) =>
    fetchJSON<{ dismissed: boolean }>(
      `/projects/${projectId}/notifications/dismiss-task/${taskId}`,
      { method: 'POST' },
    ),

  // Dependencies
  getDependencyGraph: (projectId: string) =>
    fetchJSON<DependencyGraphResponse>(`/projects/${projectId}/dependency-graph`),
  addDependency: (featureId: string, dependsOnId: string) =>
    fetchJSON<{ status: string }>(`/features/${featureId}/dependencies`, {
      method: 'POST',
      body: JSON.stringify({ depends_on_id: dependsOnId }),
    }),
  removeDependency: (featureId: string, dependsOnId: string) =>
    fetch(`${BASE_URL}/features/${featureId}/dependencies/${dependsOnId}`, {
      method: 'DELETE',
    }),

  // Search
  search: (projectId: string, q: string, limit?: number, signal?: AbortSignal) =>
    fetchJSON<SearchResponse>(
      `/projects/${projectId}/search?q=${encodeURIComponent(q)}&limit=${limit ?? 20}`,
      { signal },
    ),

  // Reorder
  reorderEpics: (projectId: string, items: { id: string; position: number }[]) =>
    fetchJSON(`/projects/${projectId}/epics/reorder`, {
      method: 'POST',
      body: JSON.stringify({ items }),
    }),

  reorderFeatures: (projectId: string, epicId: string, items: { id: string; position: number }[]) =>
    fetchJSON(`/projects/${projectId}/epics/${epicId}/features/reorder`, {
      method: 'POST',
      body: JSON.stringify({ items }),
    }),

  reorderTasks: (featureId: string, items: { id: string; position: number }[]) =>
    fetchJSON(`/features/${featureId}/tasks/reorder`, {
      method: 'POST',
      body: JSON.stringify({ items }),
    }),

  // SSE stream URL (not a fetch — used by EventSource)
  streamUrl: (projectId: string) => `${BASE_URL}/projects/${projectId}/stream`,
}
