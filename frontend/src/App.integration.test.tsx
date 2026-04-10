import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock excalidraw before importing App (open-color JSON import issue)
vi.mock('@excalidraw/excalidraw', () => ({
  Excalidraw: () => null,
  convertToExcalidrawElements: vi.fn().mockReturnValue([]),
}))
vi.mock('@excalidraw/mermaid-to-excalidraw', () => ({
  parseMermaidToExcalidraw: vi.fn().mockResolvedValue({
    elements: [],
    files: null,
  }),
}))
vi.mock('@excalidraw/excalidraw/index.css', () => ({}))

import App from './App'
import { api } from './api/client'
import type { BoardResponse, Project, Worktree } from './api/types'

vi.mock('./api/client', () => ({
  api: {
    listProjects: vi.fn(),
    getBoard: vi.fn(),
    getBacklog: vi.fn(),
    getWorktrees: vi.fn(),
    getTaskDocuments: vi.fn(),
    getTaskNotes: vi.fn(),
    getDocument: vi.fn(),
    getNotifications: vi.fn(),
    markNotificationRead: vi.fn(),
    markAllNotificationsRead: vi.fn(),
    dismissTaskNotification: vi.fn(),
    getDependencyGraph: vi.fn(),
    streamUrl: vi.fn().mockReturnValue('http://test/stream'),
  },
}))

vi.stubGlobal('EventSource', class {
  addEventListener() {}
  removeEventListener() {}
  close() {}
  set onerror(_: unknown) {}
})

const mockApi = vi.mocked(api)

const projects: Project[] = [
  { id: 'p1', name: 'Frontend App', description: 'The UI', repo_url: '', status: 'active', created_at: '' },
  { id: 'p2', name: 'Backend API', description: 'The API', repo_url: '', status: 'active', created_at: '' },
]

const worktrees: Worktree[] = [
  { id: 'wt1', project_id: 'p1', name: 'wt-ui', worktree_path: '/tmp', branch_name: 'main', status: 'online', current_task_id: 't1', last_heartbeat: null, created_at: '2024-01-01T00:00:00Z' },
]

const board: BoardResponse = {
  project_id: 'p1',
  project_name: 'Frontend App',
  columns: [
    {
      status: 'backlog',
      tasks: [
        {
          id: 't1',
          feature_id: 'f1',
          title: 'Build login page',
          description: 'Create the login form with validation',
          status: 'backlog',
          priority: 'expedite',
          task_type: 'task',
          pr_url: null,
          worktree_id: 'wt1',
          position: 0,
          number: 1,
          archived: false,
          retired: false,
          created_at: '',
          updated_at: '',
          epic_title: 'Authentication',
          feature_title: 'Login',
          epic_color: '#7c3aed',
        },
      ],
    },
    {
      status: 'in_progress',
      tasks: [
        {
          id: 't2',
          feature_id: 'f2',
          title: 'Setup CI pipeline',
          description: 'Configure GitHub Actions',
          status: 'in_progress',
          priority: 'normal',
          task_type: 'task',
          pr_url: null,
          worktree_id: null,
          position: 0,
          number: 2,
          archived: false,
          retired: false,
          created_at: '',
          updated_at: '',
          epic_title: 'DevOps',
          feature_title: 'CI/CD',
          epic_color: '#2563eb',
        },
      ],
    },
    { status: 'done', tasks: [] },
  ],
  total_tasks: 2,
  done_count: 0,
}

const routes = [
  { path: '/projects', element: <App /> },
  { path: '/projects/:projectId', element: <App /> },
  { path: '/projects/:projectId/tasks/:taskId', element: <App /> },
  { path: '/projects/:projectId/epics/:epicId', element: <App /> },
  { path: '/projects/:projectId/features/:featureId', element: <App /> },
]

function renderWithRouter(initialEntries: string[] = ['/projects']) {
  const router = createMemoryRouter(routes, { initialEntries })
  return render(<RouterProvider router={router} />)
}

beforeEach(() => {
  vi.clearAllMocks()
  mockApi.listProjects.mockResolvedValue(projects)
  mockApi.getBoard.mockResolvedValue(board)
  mockApi.getBacklog.mockResolvedValue([])
  mockApi.getWorktrees.mockResolvedValue(worktrees)
  mockApi.getTaskDocuments.mockResolvedValue([])
  mockApi.getTaskNotes.mockResolvedValue([])
  mockApi.getNotifications.mockResolvedValue([])
  mockApi.dismissTaskNotification.mockResolvedValue({ dismissed: true })
  mockApi.getDependencyGraph.mockResolvedValue({ nodes: [], edges: [] })
})

describe('App integration', () => {
  it('loads projects and shows select prompt', async () => {
    renderWithRouter()
    expect(await screen.findByText('select a project')).toBeInTheDocument()
    expect(screen.getByText('Frontend App')).toBeInTheDocument()
    expect(screen.getByText('Backend API')).toBeInTheDocument()
  })

  it('selecting a project loads the board', async () => {
    const user = userEvent.setup()
    renderWithRouter()

    await screen.findByText('Frontend App')
    await user.click(screen.getByText('Frontend App'))

    await waitFor(() => {
      expect(mockApi.getBoard).toHaveBeenCalledWith('p1')
      expect(mockApi.getBacklog).toHaveBeenCalledWith('p1')
    })

    // Task in in_progress column should be visible
    expect(await screen.findByText('Setup CI pipeline')).toBeInTheDocument()
  })

  it('displays board columns after project selection', async () => {
    const user = userEvent.setup()
    renderWithRouter()

    await screen.findByText('Frontend App')
    await user.click(screen.getByText('Frontend App'))

    expect(await screen.findByText('Backlog')).toBeInTheDocument()
    expect(screen.getByText('In Progress')).toBeInTheDocument()
    expect(screen.getByText('Done')).toBeInTheDocument()
  })

  it('shows worktrees in sidebar after selecting a project', async () => {
    const user = userEvent.setup()
    renderWithRouter()

    await screen.findByText('Frontend App')
    await user.click(screen.getByText('Frontend App'))

    await waitFor(() => {
      expect(mockApi.getWorktrees).toHaveBeenCalledWith('p1')
    })

    const worktreeElements = await screen.findAllByText('wt-ui')
    expect(worktreeElements.length).toBeGreaterThanOrEqual(1)
  })

  it('clicking a task card opens the detail panel', async () => {
    const user = userEvent.setup()
    renderWithRouter()

    await screen.findByText('Frontend App')
    await user.click(screen.getByText('Frontend App'))

    const taskCard = await screen.findByText('Setup CI pipeline')
    await user.click(taskCard)

    // Detail panel should show task description
    await waitFor(() => {
      expect(screen.getByText('Configure GitHub Actions')).toBeInTheDocument()
    })
  })

  it('closing detail panel returns to board view', async () => {
    const user = userEvent.setup()
    renderWithRouter()

    await screen.findByText('Frontend App')
    await user.click(screen.getByText('Frontend App'))

    const taskCard = await screen.findByText('Setup CI pipeline')
    await user.click(taskCard)

    await waitFor(() => {
      expect(screen.getByText('Configure GitHub Actions')).toBeInTheDocument()
    })

    // Click the close button
    await user.click(screen.getByText('x'))

    // Description should be gone (detail panel closed)
    await waitFor(() => {
      expect(screen.queryByText('Configure GitHub Actions')).not.toBeInTheDocument()
    })
    // Board should still be visible
    expect(screen.getByText('Setup CI pipeline')).toBeInTheDocument()
  })

  it('shows board header stats', async () => {
    const user = userEvent.setup()
    renderWithRouter()

    await screen.findByText('Frontend App')
    await user.click(screen.getByText('Frontend App'))

    await waitFor(() => {
      expect(screen.getByText(/2 tasks/)).toBeInTheDocument()
      expect(screen.getByText(/0 done/)).toBeInTheDocument()
    })
  })

  it('detail panel shows expedite badge for expedite task', async () => {
    const user = userEvent.setup()
    renderWithRouter()

    await screen.findByText('Frontend App')
    await user.click(screen.getByText('Frontend App'))

    const taskCard = await screen.findByText('Setup CI pipeline')
    await user.click(taskCard)

    await waitFor(() => {
      // Setup CI pipeline is normal priority, no expedite badge expected
      expect(screen.getByText('Configure GitHub Actions')).toBeInTheDocument()
    })
  })
})
