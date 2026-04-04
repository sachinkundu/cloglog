import type { BacklogEpic, BoardResponse, Document, DocumentSummary, Project, Worktree } from './types'

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
  getDocument: (id: string) => fetchJSON<Document>(`/documents/${id}`),
  getEpicDocuments: (epicId: string) =>
    fetchJSON<DocumentSummary[]>(`/documents?attached_to_type=epic&attached_to_id=${epicId}`),
  getFeatureDocuments: (featureId: string) =>
    fetchJSON<DocumentSummary[]>(`/documents?attached_to_type=feature&attached_to_id=${featureId}`),

  // SSE stream URL (not a fetch — used by EventSource)
  streamUrl: (projectId: string) => `${BASE_URL}/projects/${projectId}/stream`,
}
