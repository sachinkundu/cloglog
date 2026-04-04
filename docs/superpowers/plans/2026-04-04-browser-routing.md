# Browser Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add client-side routing so browser URL reflects selected project and open detail panel, surviving refresh and enabling back/forward navigation.

**Architecture:** Install react-router-dom, define routes in a router config, replace useState-based navigation in App.tsx with URL-driven params. Sidebar uses navigate() instead of callbacks.

**Tech Stack:** react-router-dom v7, React 19, TypeScript

---

### Task 1: Install react-router-dom

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Install**

Run: `cd /home/sachin/code/cloglog/frontend && npm install react-router-dom`

- [ ] **Step 2: Verify**

Run: `cd /home/sachin/code/cloglog/frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
cd /home/sachin/code/cloglog && git add frontend/package.json frontend/package-lock.json
git commit -m "chore: add react-router-dom for client-side routing"
```

---

### Task 2: Create router and restructure App with URL-driven navigation

This is the main task — it replaces useState navigation with URL params.

**Files:**
- Create: `frontend/src/router.tsx`
- Modify: `frontend/src/main.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Sidebar.tsx`
- Modify: `frontend/src/components/Layout.tsx`
- Modify: `frontend/src/App.integration.test.tsx`
- Modify: `frontend/src/components/Sidebar.test.tsx`
- Modify: `frontend/src/components/Layout.test.tsx`

- [ ] **Step 1: Create router.tsx**

Create `frontend/src/router.tsx`:

```typescript
import { createBrowserRouter, Navigate } from 'react-router-dom'
import App from './App'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <Navigate to="/projects" replace />,
  },
  {
    path: '/projects',
    element: <App />,
  },
  {
    path: '/projects/:projectId',
    element: <App />,
  },
  {
    path: '/projects/:projectId/epics/:epicId',
    element: <App />,
  },
  {
    path: '/projects/:projectId/features/:featureId',
    element: <App />,
  },
  {
    path: '/projects/:projectId/tasks/:taskId',
    element: <App />,
  },
])
```

- [ ] **Step 2: Update main.tsx to use router**

Replace `frontend/src/main.tsx`:

```typescript
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router-dom'
import './index.css'
import { router } from './router'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
)
```

- [ ] **Step 3: Update Sidebar to use navigate**

Replace `frontend/src/components/Sidebar.tsx`:

```typescript
import { useNavigate } from 'react-router-dom'
import type { Project, Worktree } from '../api/types'
import './Sidebar.css'

interface SidebarProps {
  projects: Project[]
  selectedProjectId: string | null
  worktrees: Worktree[]
}

export function Sidebar({ projects, selectedProjectId, worktrees }: SidebarProps) {
  const navigate = useNavigate()

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
                onClick={() => navigate(`/projects/${p.id}`)}
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
                <span className={`status-dot ${wt.status} ${wt.status === 'online' ? 'pulse' : ''}`} />
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

Note: `onSelectProject` prop is removed — navigation is now via `useNavigate`.

- [ ] **Step 4: Update Layout to remove onSelectProject**

Replace `frontend/src/components/Layout.tsx`:

```typescript
import type { ReactNode } from 'react'
import type { Project, Worktree } from '../api/types'
import { Sidebar } from './Sidebar'
import { ThemeToggle } from './ThemeToggle'
import './Layout.css'

interface LayoutProps {
  projects: Project[]
  selectedProjectId: string | null
  worktrees: Worktree[]
  children: ReactNode
}

export function Layout({ projects, selectedProjectId, worktrees, children }: LayoutProps) {
  return (
    <div className="layout">
      <Sidebar
        projects={projects}
        selectedProjectId={selectedProjectId}
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

- [ ] **Step 5: Rewrite App.tsx to use URL params**

Replace `frontend/src/App.tsx`:

```typescript
import { useCallback } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Board } from './components/Board'
import { DetailPanel } from './components/DetailPanel'
import { Layout } from './components/Layout'
import { useBoard } from './hooks/useBoard'
import { useProjects } from './hooks/useProjects'
import type { BacklogEpic } from './api/types'

export default function App() {
  const { projects, loading: projectsLoading } = useProjects()
  const { projectId, epicId, featureId, taskId } = useParams()
  const navigate = useNavigate()
  const { board, backlog, worktrees, loading: boardLoading } = useBoard(projectId ?? null)

  const detailType = epicId ? 'epic' : featureId ? 'feature' : taskId ? 'task' : null
  const detailId = epicId ?? featureId ?? taskId ?? null

  const openDetail = useCallback((type: 'epic' | 'feature' | 'task', id: string) => {
    if (!projectId) return
    const typeSegment = type === 'epic' ? 'epics' : type === 'feature' ? 'features' : 'tasks'
    navigate(`/projects/${projectId}/${typeSegment}/${id}`)
  }, [projectId, navigate])

  const closeDetail = useCallback(() => {
    if (projectId) {
      navigate(`/projects/${projectId}`)
    }
  }, [projectId, navigate])

  const handleTaskClick = useCallback((taskId: string) => {
    openDetail('task', taskId)
  }, [openDetail])

  // Build detail data from backlog/board state
  const detailData = detailType && detailId ? buildDetailData(detailType, detailId, backlog, board) : null

  return (
    <Layout
      projects={projects}
      selectedProjectId={projectId ?? null}
      worktrees={worktrees}
    >
      {!projectId && (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          flex: 1, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '14px',
        }}>
          {projectsLoading ? 'loading projects...' : 'select a project'}
        </div>
      )}

      {projectId && boardLoading && (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          flex: 1, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '14px',
        }}>
          loading board...
        </div>
      )}

      {board && !boardLoading && (
        <Board
          board={board}
          backlog={backlog}
          onTaskClick={handleTaskClick}
          onItemClick={openDetail}
        />
      )}

      {detailData && (
        <DetailPanel
          type={detailData.type}
          data={detailData.data}
          onClose={closeDetail}
          onNavigate={openDetail}
        />
      )}
    </Layout>
  )
}

function buildDetailData(
  type: 'epic' | 'feature' | 'task',
  id: string,
  backlog: BacklogEpic[],
  board: { columns: Array<{ tasks: any[] }> } | null,
): { type: 'epic' | 'feature' | 'task'; data: any } | null {
  if (type === 'epic') {
    const entry = backlog.find(e => e.epic.id === id)
    if (!entry) return null
    return {
      type: 'epic',
      data: {
        title: entry.epic.title,
        description: entry.epic.description,
        color: entry.epic.color,
        bounded_context: entry.epic.bounded_context,
        task_counts: entry.task_counts,
        number: entry.epic.number,
        features: entry.features.map(f => ({
          title: f.feature.title,
          task_counts: f.task_counts,
        })),
      },
    }
  }

  if (type === 'feature') {
    for (const entry of backlog) {
      const feat = entry.features.find(f => f.feature.id === id)
      if (feat) {
        return {
          type: 'feature',
          data: {
            title: feat.feature.title,
            description: feat.feature.description,
            epic: { title: entry.epic.title, id: entry.epic.id, color: entry.epic.color },
            task_counts: feat.task_counts,
            number: feat.feature.number,
            tasks: feat.tasks.map(t => ({ id: t.id, title: t.title, status: t.status })),
          },
        }
      }
    }
    return null
  }

  // Task — search board columns then backlog
  if (board) {
    for (const col of board.columns) {
      const task = col.tasks.find((t: any) => t.id === id)
      if (task) {
        const epicInfo = findEpicForTask(backlog, id, task.epic_title, task.epic_color)
        const featureInfo = findFeatureForTask(backlog, id, task.feature_title)
        return {
          type: 'task',
          data: {
            title: task.title,
            description: task.description,
            status: task.status,
            priority: task.priority,
            epic: epicInfo,
            feature: featureInfo,
            worktree_id: task.worktree_id,
            number: task.number,
          },
        }
      }
    }
  }
  for (const entry of backlog) {
    for (const feat of entry.features) {
      const t = feat.tasks.find(bt => bt.id === id)
      if (t) {
        return {
          type: 'task',
          data: {
            title: t.title,
            description: '',
            status: t.status,
            priority: t.priority,
            epic: { title: entry.epic.title, id: entry.epic.id, color: entry.epic.color },
            feature: { title: feat.feature.title, id: feat.feature.id },
            worktree_id: null,
            number: t.number,
          },
        }
      }
    }
  }
  return null
}

function findEpicForTask(backlog: BacklogEpic[], taskId: string, fallbackTitle: string, fallbackColor: string) {
  for (const e of backlog) {
    for (const f of e.features) {
      if (f.tasks.some(t => t.id === taskId)) {
        return { title: e.epic.title, id: e.epic.id, color: e.epic.color }
      }
    }
  }
  return { title: fallbackTitle, id: '', color: fallbackColor }
}

function findFeatureForTask(backlog: BacklogEpic[], taskId: string, fallbackTitle: string) {
  for (const e of backlog) {
    for (const f of e.features) {
      if (f.tasks.some(t => t.id === taskId)) {
        return { title: f.feature.title, id: f.feature.id }
      }
    }
  }
  return { title: fallbackTitle, id: '' }
}
```

- [ ] **Step 6: Update test files**

All test files that render `<App />`, `<Sidebar />`, or `<Layout />` need to be wrapped in a router context. Use `MemoryRouter` from react-router-dom for tests.

**Sidebar.test.tsx** — remove `onSelectProject` prop, wrap renders in `MemoryRouter`:

```typescript
import { MemoryRouter } from 'react-router-dom'

// In each render call:
render(
  <MemoryRouter>
    <Sidebar projects={mockProjects} selectedProjectId={null} worktrees={[]} />
  </MemoryRouter>
)
```

Remove the test for `onSelectProject` callback (it now navigates instead). Replace with a test that the project button exists and is clickable.

**Layout.test.tsx** — remove `onSelectProject` prop, wrap in `MemoryRouter`:

```typescript
import { MemoryRouter } from 'react-router-dom'

render(
  <MemoryRouter>
    <Layout projects={[]} selectedProjectId={null} worktrees={[]}>
      <div>content</div>
    </Layout>
  </MemoryRouter>
)
```

**App.integration.test.tsx** — replace `render(<App />)` with `render(<MemoryRouter initialEntries={['/']}><App /></MemoryRouter>)`. For tests that need a selected project, use `initialEntries={['/projects/p1']}`.

Import `MemoryRouter` at the top of each file:
```typescript
import { MemoryRouter } from 'react-router-dom'
```

- [ ] **Step 7: Run all frontend tests**

Run: `cd /home/sachin/code/cloglog/frontend && npx vitest run`
Expected: All pass

- [ ] **Step 8: TypeScript check**

Run: `cd /home/sachin/code/cloglog/frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 9: Commit**

```bash
cd /home/sachin/code/cloglog && git add frontend/src/
git commit -m "feat(frontend): add browser routing with URL state for project and detail panel"
```

---

### Task 3: Run quality gate

- [ ] **Step 1: Backend quality**

Run: `make quality`
Expected: PASSED

- [ ] **Step 2: Frontend**

Run: `cd /home/sachin/code/cloglog/frontend && npx tsc --noEmit && npx vitest run`
Expected: All pass

- [ ] **Step 3: Manual verification**

Start dev servers:
```bash
make run-backend &
cd frontend && npm run dev
```

Verify:
- Open `http://localhost:5173` — redirects to `/projects`
- Click a project — URL changes to `/projects/{id}`
- Refresh — project stays selected
- Click a task — URL changes to `/projects/{id}/tasks/{tid}`
- Refresh — task detail panel reopens
- Click back button — returns to board without detail panel
- Click an epic in backlog — URL changes to `/projects/{id}/epics/{eid}`
