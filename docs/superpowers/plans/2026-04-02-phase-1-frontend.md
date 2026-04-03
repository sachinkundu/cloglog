# Phase 1: Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the cloglog dashboard — themed React SPA with sidebar (project list, agent roster), Kanban board with task cards, SSE real-time updates, and card detail view with document viewer.

**Architecture:** React 18 SPA built with Vite. No component library — custom components with CSS variables for theming. API client module for REST calls. SSE hook for real-time updates. Layout: sidebar + board.

**Tech Stack:** React 19, TypeScript, Vite, Vitest, @testing-library/react

**Worktree:** `wt-frontend` — only touch `frontend/`

**Dependency:** Backend API must be running for manual testing, but component tests use mocked API responses.

**Design spec reference:** See `docs/superpowers/specs/2026-03-31-cloglog-design.md` sections "Frontend" and "Design Language" for typography, colors, and layout details.

---

## File Structure

| File | Responsibility |
|------|---------------|
| `frontend/src/api/client.ts` | API client — typed fetch wrappers for all endpoints |
| `frontend/src/api/types.ts` | TypeScript types matching backend schemas |
| `frontend/src/hooks/useSSE.ts` | SSE subscription hook for real-time updates |
| `frontend/src/hooks/useProjects.ts` | Project list fetching hook |
| `frontend/src/hooks/useBoard.ts` | Board data fetching + SSE integration |
| `frontend/src/theme/variables.css` | CSS custom properties — dark + light themes |
| `frontend/src/theme/fonts.css` | Font-face declarations |
| `frontend/src/components/Layout.tsx` | Sidebar + board layout shell |
| `frontend/src/components/Sidebar.tsx` | Project list + agent roster |
| `frontend/src/components/Board.tsx` | Kanban columns container |
| `frontend/src/components/Column.tsx` | Single Kanban column |
| `frontend/src/components/TaskCard.tsx` | Task card with breadcrumb + doc chips |
| `frontend/src/components/CardDetail.tsx` | Slide-out task detail with document viewer |
| `frontend/src/components/ThemeToggle.tsx` | Dark/light theme toggle |
| `frontend/src/components/BoardHeader.tsx` | Project name + summary stats |
| `frontend/src/App.tsx` | Root component with routing |

---

### Task 1: TypeScript Types + API Client

**Files:**
- Create: `frontend/src/api/types.ts`
- Create: `frontend/src/api/client.ts`

- [ ] **Step 1: Define types**

```typescript
// frontend/src/api/types.ts

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
```

- [ ] **Step 2: Implement API client**

```typescript
// frontend/src/api/client.ts

import type { BoardResponse, Document, DocumentSummary, Project, Worktree } from './types'

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

  // Documents
  getTaskDocuments: (taskId: string) => fetchJSON<DocumentSummary[]>(`/tasks/${taskId}/documents`),
  getDocument: (id: string) => fetchJSON<Document>(`/documents/${id}`),

  // SSE stream URL (not a fetch — used by EventSource)
  streamUrl: (projectId: string) => `${BASE_URL}/projects/${projectId}/stream`,
}
```

- [ ] **Step 3: Commit**

```bash
cd /home/sachin/code/cloglog/frontend
git add src/api/
git commit -m "feat(frontend): add TypeScript types and API client"
```

---

### Task 2: Theme System

**Files:**
- Create: `frontend/src/theme/variables.css`
- Create: `frontend/src/theme/fonts.css`
- Modify: `frontend/src/index.css`

- [ ] **Step 1: Create CSS variables for dark + light themes**

```css
/* frontend/src/theme/variables.css */

:root {
  /* Dark theme (default) */
  --bg-primary: #06080d;
  --bg-secondary: #0c1017;
  --bg-tertiary: #131820;
  --bg-card: #161c26;
  --bg-card-hover: #1a2230;
  --bg-sidebar: #0a0e14;

  --text-primary: #e2e8f0;
  --text-secondary: #94a3b8;
  --text-muted: #64748b;

  --accent: #22d3ee;
  --accent-hover: #06b6d4;
  --active: #10b981;
  --working: #f59e0b;
  --review: #a78bfa;
  --danger: #ef4444;
  --blocked: #f97316;

  --border: #1e293b;
  --border-subtle: #162032;

  --shadow-card: 0 1px 3px rgba(0, 0, 0, 0.4);
  --shadow-card-hover: 0 4px 12px rgba(0, 0, 0, 0.5);

  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;

  --font-display: 'Bricolage Grotesque', system-ui, sans-serif;
  --font-body: 'DM Sans', system-ui, sans-serif;
  --font-mono: 'IBM Plex Mono', monospace;

  /* Column colors */
  --col-backlog: #64748b;
  --col-assigned: #22d3ee;
  --col-in-progress: #f59e0b;
  --col-review: #a78bfa;
  --col-done: #10b981;
  --col-blocked: #f97316;

  /* Doc chip colors */
  --chip-spec: #22d3ee;
  --chip-plan: #a78bfa;
  --chip-design: #f59e0b;
  --chip-other: #64748b;
}

[data-theme="light"] {
  --bg-primary: #f8fafc;
  --bg-secondary: #f1f5f9;
  --bg-tertiary: #e2e8f0;
  --bg-card: #ffffff;
  --bg-card-hover: #f8fafc;
  --bg-sidebar: #f1f5f9;

  --text-primary: #0f172a;
  --text-secondary: #475569;
  --text-muted: #94a3b8;

  --accent: #0891b2;
  --accent-hover: #0e7490;
  --active: #059669;
  --working: #d97706;
  --review: #7c3aed;

  --border: #e2e8f0;
  --border-subtle: #f1f5f9;

  --shadow-card: 0 1px 3px rgba(0, 0, 0, 0.1);
  --shadow-card-hover: 0 4px 12px rgba(0, 0, 0, 0.15);
}
```

- [ ] **Step 2: Create font imports**

```css
/* frontend/src/theme/fonts.css */

@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:wght@400;600;700&family=DM+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');
```

- [ ] **Step 3: Replace index.css with base styles**

```css
/* frontend/src/index.css */

@import './theme/fonts.css';
@import './theme/variables.css';

*,
*::before,
*::after {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

html, body, #root {
  height: 100%;
}

body {
  font-family: var(--font-body);
  background: var(--bg-primary);
  color: var(--text-primary);
  -webkit-font-smoothing: antialiased;
}

h1, h2, h3, h4 {
  font-family: var(--font-display);
}

code, pre {
  font-family: var(--font-mono);
}

a {
  color: var(--accent);
  text-decoration: none;
}

a:hover {
  color: var(--accent-hover);
}

/* Pulse animation for active worktrees */
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.pulse {
  animation: pulse 2s ease-in-out infinite;
}

/* Scrollbar styling */
::-webkit-scrollbar {
  width: 6px;
}

::-webkit-scrollbar-track {
  background: var(--bg-secondary);
}

::-webkit-scrollbar-thumb {
  background: var(--border);
  border-radius: 3px;
}
```

- [ ] **Step 4: Commit**

```bash
cd /home/sachin/code/cloglog/frontend
git add src/theme/ src/index.css
git commit -m "feat(frontend): add dark/light theme system with CSS variables"
```

---

### Task 3: SSE Hook

**Files:**
- Create: `frontend/src/hooks/useSSE.ts`
- Test: `frontend/src/hooks/useSSE.test.ts`

- [ ] **Step 1: Write test**

```typescript
// frontend/src/hooks/useSSE.test.ts
import { renderHook, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useSSE } from './useSSE'

// Mock EventSource
class MockEventSource {
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  readyState = 0
  url: string
  close = vi.fn()

  constructor(url: string) {
    this.url = url
    MockEventSource.instances.push(this)
  }

  addEventListener(type: string, handler: (event: MessageEvent) => void) {
    // Store handlers by event type
    if (!this._handlers[type]) this._handlers[type] = []
    this._handlers[type].push(handler)
  }

  removeEventListener() {}

  _handlers: Record<string, Array<(event: MessageEvent) => void>> = {}
  static instances: MockEventSource[] = []
  static reset() { MockEventSource.instances = [] }
}

beforeEach(() => {
  MockEventSource.reset()
  vi.stubGlobal('EventSource', MockEventSource)
})

describe('useSSE', () => {
  it('connects to the correct URL', () => {
    renderHook(() => useSSE('project-123', vi.fn()))
    expect(MockEventSource.instances).toHaveLength(1)
    expect(MockEventSource.instances[0].url).toContain('project-123')
  })

  it('closes connection on unmount', () => {
    const { unmount } = renderHook(() => useSSE('project-123', vi.fn()))
    unmount()
    expect(MockEventSource.instances[0].close).toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sachin/code/cloglog/frontend && npx vitest run src/hooks/useSSE.test.ts`
Expected: Fail — module not found.

- [ ] **Step 3: Implement SSE hook**

```typescript
// frontend/src/hooks/useSSE.ts
import { useEffect, useRef } from 'react'
import { api } from '../api/client'
import type { SSEEvent } from '../api/types'

export function useSSE(
  projectId: string | null,
  onEvent: (event: SSEEvent) => void,
) {
  const onEventRef = useRef(onEvent)
  onEventRef.current = onEvent

  useEffect(() => {
    if (!projectId) return

    const url = api.streamUrl(projectId)
    const source = new EventSource(url)

    const eventTypes = [
      'task_status_changed',
      'worktree_online',
      'worktree_offline',
      'document_attached',
    ] as const

    for (const type of eventTypes) {
      source.addEventListener(type, (event: MessageEvent) => {
        try {
          const data = JSON.parse(event.data)
          onEventRef.current({ type, data })
        } catch {
          // Ignore malformed events
        }
      })
    }

    source.onerror = () => {
      // EventSource auto-reconnects; no action needed
    }

    return () => {
      source.close()
    }
  }, [projectId])
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sachin/code/cloglog/frontend && npx vitest run src/hooks/useSSE.test.ts`
Expected: Pass.

- [ ] **Step 5: Commit**

```bash
cd /home/sachin/code/cloglog/frontend
git add src/hooks/useSSE.ts src/hooks/useSSE.test.ts
git commit -m "feat(frontend): add SSE hook for real-time board updates"
```

---

### Task 4: Data Hooks

**Files:**
- Create: `frontend/src/hooks/useProjects.ts`
- Create: `frontend/src/hooks/useBoard.ts`

- [ ] **Step 1: Implement project list hook**

```typescript
// frontend/src/hooks/useProjects.ts
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Project } from '../api/types'

export function useProjects() {
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api.listProjects()
      .then(data => { if (!cancelled) setProjects(data) })
      .catch(err => { if (!cancelled) setError(err.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  return { projects, loading, error }
}
```

- [ ] **Step 2: Implement board data hook with SSE integration**

```typescript
// frontend/src/hooks/useBoard.ts
import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { BoardResponse, SSEEvent, Worktree } from '../api/types'
import { useSSE } from './useSSE'

export function useBoard(projectId: string | null) {
  const [board, setBoard] = useState<BoardResponse | null>(null)
  const [worktrees, setWorktrees] = useState<Worktree[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchBoard = useCallback(async () => {
    if (!projectId) return
    setLoading(true)
    try {
      const [boardData, wtData] = await Promise.all([
        api.getBoard(projectId),
        api.getWorktrees(projectId),
      ])
      setBoard(boardData)
      setWorktrees(wtData)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load board')
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    fetchBoard()
  }, [fetchBoard])

  // Re-fetch on SSE events
  const handleSSE = useCallback((_event: SSEEvent) => {
    fetchBoard()
  }, [fetchBoard])

  useSSE(projectId, handleSSE)

  return { board, worktrees, loading, error, refetch: fetchBoard }
}
```

- [ ] **Step 3: Commit**

```bash
cd /home/sachin/code/cloglog/frontend
git add src/hooks/useProjects.ts src/hooks/useBoard.ts
git commit -m "feat(frontend): add data hooks for projects and board"
```

---

### Task 5: Layout + Sidebar + Theme Toggle

**Files:**
- Create: `frontend/src/components/ThemeToggle.tsx`
- Create: `frontend/src/components/Sidebar.tsx`
- Create: `frontend/src/components/Layout.tsx`
- Create: `frontend/src/components/Layout.css`
- Create: `frontend/src/components/Sidebar.css`

- [ ] **Step 1: Implement ThemeToggle**

```tsx
// frontend/src/components/ThemeToggle.tsx
import { useEffect, useState } from 'react'

export function ThemeToggle() {
  const [dark, setDark] = useState(true)

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light')
  }, [dark])

  return (
    <button
      onClick={() => setDark(d => !d)}
      style={{
        background: 'none',
        border: '1px solid var(--border)',
        color: 'var(--text-secondary)',
        borderRadius: 'var(--radius-sm)',
        padding: '4px 8px',
        cursor: 'pointer',
        fontFamily: 'var(--font-mono)',
        fontSize: '12px',
      }}
      aria-label="Toggle theme"
    >
      {dark ? 'light' : 'dark'}
    </button>
  )
}
```

- [ ] **Step 2: Implement Sidebar**

```tsx
// frontend/src/components/Sidebar.tsx
import type { Project, Worktree } from '../api/types'
import './Sidebar.css'

interface SidebarProps {
  projects: Project[]
  selectedProjectId: string | null
  onSelectProject: (id: string) => void
  worktrees: Worktree[]
}

export function Sidebar({ projects, selectedProjectId, onSelectProject, worktrees }: SidebarProps) {
  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <h1 className="sidebar-title">cloglog</h1>
      </div>

      <section className="sidebar-section">
        <h2 className="sidebar-section-title">Projects</h2>
        <ul className="project-list">
          {projects.map(p => (
            <li key={p.id}>
              <button
                className={`project-item ${p.id === selectedProjectId ? 'selected' : ''}`}
                onClick={() => onSelectProject(p.id)}
              >
                <span className={`status-dot ${p.status}`} />
                <span className="project-name">{p.name}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>

      {selectedProjectId && worktrees.length > 0 && (
        <section className="sidebar-section">
          <h2 className="sidebar-section-title">Agents</h2>
          <ul className="worktree-list">
            {worktrees.map(wt => (
              <li key={wt.id} className="worktree-item">
                <span className={`status-dot ${wt.status} ${wt.status === 'active' ? 'pulse' : ''}`} />
                <span className="worktree-name">{wt.name}</span>
                <span className="worktree-status">{wt.status}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </aside>
  )
}
```

- [ ] **Step 3: Create Sidebar CSS**

```css
/* frontend/src/components/Sidebar.css */

.sidebar {
  width: 260px;
  min-width: 260px;
  background: var(--bg-sidebar);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

.sidebar-header {
  padding: 20px 16px 12px;
  border-bottom: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.sidebar-title {
  font-family: var(--font-display);
  font-size: 20px;
  font-weight: 700;
  color: var(--accent);
  letter-spacing: -0.5px;
}

.sidebar-section {
  padding: 12px 0;
}

.sidebar-section-title {
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: var(--text-muted);
  padding: 0 16px 8px;
}

.project-list,
.worktree-list {
  list-style: none;
}

.project-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 16px;
  background: none;
  border: none;
  color: var(--text-secondary);
  font-family: var(--font-body);
  font-size: 14px;
  cursor: pointer;
  text-align: left;
}

.project-item:hover {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

.project-item.selected {
  background: var(--bg-tertiary);
  color: var(--accent);
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-dot.active { background: var(--active); }
.status-dot.paused { background: var(--working); }
.status-dot.completed { background: var(--text-muted); }
.status-dot.idle { background: var(--text-muted); }
.status-dot.offline { background: var(--danger); }

.worktree-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 16px;
  font-size: 13px;
}

.worktree-name {
  color: var(--text-secondary);
  font-family: var(--font-mono);
  font-size: 12px;
}

.worktree-status {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
}
```

- [ ] **Step 4: Implement Layout**

```tsx
// frontend/src/components/Layout.tsx
import type { ReactNode } from 'react'
import type { Project, Worktree } from '../api/types'
import { Sidebar } from './Sidebar'
import { ThemeToggle } from './ThemeToggle'
import './Layout.css'

interface LayoutProps {
  projects: Project[]
  selectedProjectId: string | null
  onSelectProject: (id: string) => void
  worktrees: Worktree[]
  children: ReactNode
}

export function Layout({ projects, selectedProjectId, onSelectProject, worktrees, children }: LayoutProps) {
  return (
    <div className="layout">
      <Sidebar
        projects={projects}
        selectedProjectId={selectedProjectId}
        onSelectProject={onSelectProject}
        worktrees={worktrees}
      />
      <main className="main-content">
        <div className="main-header">
          <ThemeToggle />
        </div>
        {children}
      </main>
    </div>
  )
}
```

```css
/* frontend/src/components/Layout.css */

.layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

.main-content {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

.main-header {
  display: flex;
  justify-content: flex-end;
  padding: 12px 20px;
  border-bottom: 1px solid var(--border-subtle);
}
```

- [ ] **Step 5: Commit**

```bash
cd /home/sachin/code/cloglog/frontend
git add src/components/ThemeToggle.tsx src/components/Sidebar.tsx src/components/Sidebar.css src/components/Layout.tsx src/components/Layout.css
git commit -m "feat(frontend): add layout, sidebar, and theme toggle"
```

---

### Task 6: Kanban Board + Task Cards

**Files:**
- Create: `frontend/src/components/BoardHeader.tsx`
- Create: `frontend/src/components/Board.tsx`
- Create: `frontend/src/components/Board.css`
- Create: `frontend/src/components/Column.tsx`
- Create: `frontend/src/components/Column.css`
- Create: `frontend/src/components/TaskCard.tsx`
- Create: `frontend/src/components/TaskCard.css`

- [ ] **Step 1: Implement BoardHeader**

```tsx
// frontend/src/components/BoardHeader.tsx
import type { BoardResponse } from '../api/types'

interface BoardHeaderProps {
  board: BoardResponse
}

export function BoardHeader({ board }: BoardHeaderProps) {
  const pct = board.total_tasks > 0
    ? Math.round((board.done_count / board.total_tasks) * 100)
    : 0

  return (
    <div style={{
      padding: '20px 24px 12px',
      display: 'flex',
      alignItems: 'baseline',
      gap: '16px',
    }}>
      <h2 style={{
        fontFamily: 'var(--font-display)',
        fontSize: '24px',
        fontWeight: 700,
        color: 'var(--text-primary)',
      }}>
        {board.project_name}
      </h2>
      <span style={{
        fontFamily: 'var(--font-mono)',
        fontSize: '13px',
        color: 'var(--text-muted)',
      }}>
        {board.total_tasks} tasks &middot; {board.done_count} done &middot; {pct}%
      </span>
    </div>
  )
}
```

- [ ] **Step 2: Implement TaskCard**

```tsx
// frontend/src/components/TaskCard.tsx
import type { TaskCard as TaskCardType } from '../api/types'
import './TaskCard.css'

interface TaskCardProps {
  task: TaskCardType
  onClick: () => void
}

export function TaskCard({ task, onClick }: TaskCardProps) {
  return (
    <div className="task-card" onClick={onClick} role="button" tabIndex={0}>
      <div className="task-breadcrumb">
        {task.epic_title} / {task.feature_title}
      </div>
      <div className="task-title">{task.title}</div>
      <div className="task-meta">
        {task.priority === 'expedite' && (
          <span className="task-priority">expedite</span>
        )}
        {task.worktree_id && (
          <span className="task-worktree">agent assigned</span>
        )}
      </div>
    </div>
  )
}
```

```css
/* frontend/src/components/TaskCard.css */

.task-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 12px;
  cursor: pointer;
  transition: box-shadow 0.15s ease, transform 0.15s ease;
  box-shadow: var(--shadow-card);
}

.task-card:hover {
  box-shadow: var(--shadow-card-hover);
  transform: translateY(-1px);
}

.task-breadcrumb {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
  margin-bottom: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.task-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
  line-height: 1.3;
}

.task-meta {
  display: flex;
  gap: 6px;
  margin-top: 8px;
  flex-wrap: wrap;
}

.task-priority {
  font-family: var(--font-mono);
  font-size: 10px;
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  background: var(--danger);
  color: white;
}

.task-worktree {
  font-family: var(--font-mono);
  font-size: 10px;
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  background: var(--bg-tertiary);
  color: var(--text-secondary);
}
```

- [ ] **Step 3: Implement Column**

```tsx
// frontend/src/components/Column.tsx
import type { BoardColumn as BoardColumnType } from '../api/types'
import { TaskCard } from './TaskCard'
import './Column.css'

interface ColumnProps {
  column: BoardColumnType
  onTaskClick: (taskId: string) => void
}

const COLUMN_LABELS: Record<string, string> = {
  backlog: 'Backlog',
  assigned: 'Assigned',
  in_progress: 'In Progress',
  review: 'Review',
  done: 'Done',
  blocked: 'Blocked',
}

export function Column({ column, onTaskClick }: ColumnProps) {
  return (
    <div className="column">
      <div className="column-header">
        <span className={`column-dot col-${column.status}`} />
        <span className="column-title">{COLUMN_LABELS[column.status] ?? column.status}</span>
        <span className="column-count">{column.tasks.length}</span>
      </div>
      <div className="column-tasks">
        {column.tasks.map(task => (
          <TaskCard key={task.id} task={task} onClick={() => onTaskClick(task.id)} />
        ))}
      </div>
    </div>
  )
}
```

```css
/* frontend/src/components/Column.css */

.column {
  min-width: 280px;
  max-width: 320px;
  flex: 1;
  display: flex;
  flex-direction: column;
}

.column-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  margin-bottom: 8px;
}

.column-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.column-dot.col-backlog { background: var(--col-backlog); }
.column-dot.col-assigned { background: var(--col-assigned); }
.column-dot.col-in_progress { background: var(--col-in-progress); }
.column-dot.col-review { background: var(--col-review); }
.column-dot.col-done { background: var(--col-done); }
.column-dot.col-blocked { background: var(--col-blocked); }

.column-title {
  font-family: var(--font-display);
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.column-count {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
  margin-left: auto;
}

.column-tasks {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 0 4px;
  overflow-y: auto;
  flex: 1;
}
```

- [ ] **Step 4: Implement Board**

```tsx
// frontend/src/components/Board.tsx
import type { BoardResponse } from '../api/types'
import { BoardHeader } from './BoardHeader'
import { Column } from './Column'
import './Board.css'

interface BoardProps {
  board: BoardResponse
  onTaskClick: (taskId: string) => void
}

export function Board({ board, onTaskClick }: BoardProps) {
  return (
    <div className="board">
      <BoardHeader board={board} />
      <div className="board-columns">
        {board.columns.map(col => (
          <Column key={col.status} column={col} onTaskClick={onTaskClick} />
        ))}
      </div>
    </div>
  )
}
```

```css
/* frontend/src/components/Board.css */

.board {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.board-columns {
  display: flex;
  gap: 12px;
  padding: 12px 24px 24px;
  overflow-x: auto;
  flex: 1;
}
```

- [ ] **Step 5: Commit**

```bash
cd /home/sachin/code/cloglog/frontend
git add src/components/BoardHeader.tsx src/components/Board.tsx src/components/Board.css src/components/Column.tsx src/components/Column.css src/components/TaskCard.tsx src/components/TaskCard.css
git commit -m "feat(frontend): add Kanban board, columns, and task cards"
```

---

### Task 7: Card Detail View

**Files:**
- Create: `frontend/src/components/CardDetail.tsx`
- Create: `frontend/src/components/CardDetail.css`

- [ ] **Step 1: Implement card detail slide-out**

```tsx
// frontend/src/components/CardDetail.tsx
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Document, DocumentSummary, TaskCard } from '../api/types'
import './CardDetail.css'

interface CardDetailProps {
  task: TaskCard
  onClose: () => void
}

export function CardDetail({ task, onClose }: CardDetailProps) {
  const [docs, setDocs] = useState<DocumentSummary[]>([])
  const [selectedDoc, setSelectedDoc] = useState<Document | null>(null)

  useEffect(() => {
    api.getTaskDocuments(task.id).then(setDocs).catch(() => {})
  }, [task.id])

  const openDoc = async (docId: string) => {
    const doc = await api.getDocument(docId)
    setSelectedDoc(doc)
  }

  return (
    <div className="card-detail-overlay" onClick={onClose}>
      <div className="card-detail" onClick={e => e.stopPropagation()}>
        <div className="card-detail-header">
          <div className="card-detail-breadcrumb">
            {task.epic_title} / {task.feature_title}
          </div>
          <h2 className="card-detail-title">{task.title}</h2>
          <div className="card-detail-status">
            <span className={`status-badge ${task.status}`}>{task.status}</span>
            {task.priority === 'expedite' && (
              <span className="status-badge expedite">expedite</span>
            )}
          </div>
          <button className="card-detail-close" onClick={onClose}>x</button>
        </div>

        {task.description && (
          <div className="card-detail-section">
            <h3>Description</h3>
            <p className="card-detail-description">{task.description}</p>
          </div>
        )}

        {docs.length > 0 && (
          <div className="card-detail-section">
            <h3>Documents</h3>
            <div className="doc-chips">
              {docs.map(doc => (
                <button
                  key={doc.id}
                  className={`doc-chip chip-${doc.type}`}
                  onClick={() => openDoc(doc.id)}
                >
                  {doc.type}: {doc.title}
                </button>
              ))}
            </div>
          </div>
        )}

        {selectedDoc && (
          <div className="card-detail-section">
            <h3>{selectedDoc.title}</h3>
            <pre className="doc-content">{selectedDoc.content}</pre>
          </div>
        )}
      </div>
    </div>
  )
}
```

```css
/* frontend/src/components/CardDetail.css */

.card-detail-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  justify-content: flex-end;
  z-index: 100;
}

.card-detail {
  width: 520px;
  max-width: 90vw;
  height: 100%;
  background: var(--bg-secondary);
  border-left: 1px solid var(--border);
  overflow-y: auto;
  padding: 24px;
  position: relative;
}

.card-detail-header {
  margin-bottom: 20px;
}

.card-detail-breadcrumb {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 8px;
}

.card-detail-title {
  font-family: var(--font-display);
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.card-detail-status {
  display: flex;
  gap: 8px;
}

.status-badge {
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 3px 8px;
  border-radius: var(--radius-sm);
  background: var(--bg-tertiary);
  color: var(--text-secondary);
}

.status-badge.in_progress { color: var(--working); border: 1px solid var(--working); }
.status-badge.review { color: var(--review); border: 1px solid var(--review); }
.status-badge.done { color: var(--active); border: 1px solid var(--active); }
.status-badge.expedite { color: var(--danger); border: 1px solid var(--danger); }

.card-detail-close {
  position: absolute;
  top: 16px;
  right: 16px;
  background: none;
  border: 1px solid var(--border);
  color: var(--text-secondary);
  border-radius: var(--radius-sm);
  width: 28px;
  height: 28px;
  cursor: pointer;
  font-family: var(--font-mono);
}

.card-detail-section {
  margin-bottom: 20px;
}

.card-detail-section h3 {
  font-family: var(--font-mono);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: var(--text-muted);
  margin-bottom: 8px;
}

.card-detail-description {
  font-size: 14px;
  color: var(--text-secondary);
  line-height: 1.5;
}

.doc-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.doc-chip {
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 4px 10px;
  border-radius: var(--radius-sm);
  border: none;
  cursor: pointer;
  color: white;
}

.chip-spec { background: var(--chip-spec); }
.chip-plan { background: var(--chip-plan); }
.chip-design { background: var(--chip-design); }
.chip-other { background: var(--chip-other); }

.doc-content {
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--text-secondary);
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 16px;
  white-space: pre-wrap;
  word-wrap: break-word;
  max-height: 400px;
  overflow-y: auto;
}
```

- [ ] **Step 2: Commit**

```bash
cd /home/sachin/code/cloglog/frontend
git add src/components/CardDetail.tsx src/components/CardDetail.css
git commit -m "feat(frontend): add card detail slide-out with document viewer"
```

---

### Task 8: App Root — Wire Everything Together

**Files:**
- Modify: `frontend/src/App.tsx`
- Delete: `frontend/src/App.css`

- [ ] **Step 1: Rewrite App.tsx**

```tsx
// frontend/src/App.tsx
import { useCallback, useState } from 'react'
import type { TaskCard as TaskCardType } from './api/types'
import { Board } from './components/Board'
import { CardDetail } from './components/CardDetail'
import { Layout } from './components/Layout'
import { useBoard } from './hooks/useBoard'
import { useProjects } from './hooks/useProjects'

export default function App() {
  const { projects, loading: projectsLoading } = useProjects()
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null)
  const { board, worktrees, loading: boardLoading } = useBoard(selectedProjectId)
  const [selectedTask, setSelectedTask] = useState<TaskCardType | null>(null)

  const handleTaskClick = useCallback((taskId: string) => {
    if (!board) return
    for (const col of board.columns) {
      const task = col.tasks.find(t => t.id === taskId)
      if (task) {
        setSelectedTask(task)
        return
      }
    }
  }, [board])

  return (
    <Layout
      projects={projects}
      selectedProjectId={selectedProjectId}
      onSelectProject={setSelectedProjectId}
      worktrees={worktrees}
    >
      {!selectedProjectId && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flex: 1,
          color: 'var(--text-muted)',
          fontFamily: 'var(--font-mono)',
          fontSize: '14px',
        }}>
          {projectsLoading ? 'loading projects...' : 'select a project'}
        </div>
      )}

      {selectedProjectId && boardLoading && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flex: 1,
          color: 'var(--text-muted)',
          fontFamily: 'var(--font-mono)',
          fontSize: '14px',
        }}>
          loading board...
        </div>
      )}

      {board && !boardLoading && (
        <Board board={board} onTaskClick={handleTaskClick} />
      )}

      {selectedTask && (
        <CardDetail task={selectedTask} onClose={() => setSelectedTask(null)} />
      )}
    </Layout>
  )
}
```

- [ ] **Step 2: Delete old App.css**

```bash
rm -f /home/sachin/code/cloglog/frontend/src/App.css
```

- [ ] **Step 3: Update App.test.tsx**

```tsx
// frontend/src/App.test.tsx
import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import App from './App'

// Mock the API
vi.mock('./api/client', () => ({
  api: {
    listProjects: vi.fn().mockResolvedValue([]),
    getBoard: vi.fn().mockResolvedValue(null),
    getWorktrees: vi.fn().mockResolvedValue([]),
    streamUrl: vi.fn().mockReturnValue('http://test/stream'),
  },
}))

// Mock EventSource
vi.stubGlobal('EventSource', class {
  addEventListener() {}
  removeEventListener() {}
  close() {}
  set onerror(_: unknown) {}
})

describe('App', () => {
  it('renders the sidebar title', () => {
    render(<App />)
    expect(screen.getByText('cloglog')).toBeInTheDocument()
  })

  it('shows select prompt when no project selected', () => {
    render(<App />)
    expect(screen.getByText('select a project')).toBeInTheDocument()
  })
})
```

- [ ] **Step 4: Run tests**

Run: `cd /home/sachin/code/cloglog/frontend && npx vitest run`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
cd /home/sachin/code/cloglog/frontend
git add src/App.tsx src/App.test.tsx
git rm -f src/App.css 2>/dev/null; true
git add -A
git commit -m "feat(frontend): wire up App with layout, board, and card detail"
```

---

### Task 9: Final Quality Check

- [ ] **Step 1: Run all frontend checks**

```bash
cd /home/sachin/code/cloglog/frontend
npx vitest run
npx tsc --noEmit
```

Expected: All tests pass, no type errors.

- [ ] **Step 2: Verify build works**

```bash
cd /home/sachin/code/cloglog/frontend && npm run build
```

Expected: Build succeeds.
