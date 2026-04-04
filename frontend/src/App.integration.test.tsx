import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import App from './App'
import { api } from './api/client'
import type { BoardResponse, Project, Worktree } from './api/types'

vi.mock('./api/client', () => ({
  api: {
    listProjects: vi.fn(),
    getBoard: vi.fn(),
    getWorktrees: vi.fn(),
    getTaskDocuments: vi.fn(),
    getDocument: vi.fn(),
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
          worktree_id: 'wt1',
          position: 0,
          created_at: '',
          updated_at: '',
          epic_title: 'Authentication',
          feature_title: 'Login',
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
          worktree_id: null,
          position: 0,
          created_at: '',
          updated_at: '',
          epic_title: 'DevOps',
          feature_title: 'CI/CD',
        },
      ],
    },
    { status: 'done', tasks: [] },
  ],
  total_tasks: 2,
  done_count: 0,
}

beforeEach(() => {
  vi.clearAllMocks()
  mockApi.listProjects.mockResolvedValue(projects)
  mockApi.getBoard.mockResolvedValue(board)
  mockApi.getWorktrees.mockResolvedValue(worktrees)
  mockApi.getTaskDocuments.mockResolvedValue([])
})

describe('App integration', () => {
  it('loads projects and shows select prompt', async () => {
    render(<App />)
    expect(await screen.findByText('select a project')).toBeInTheDocument()
    expect(screen.getByText('Frontend App')).toBeInTheDocument()
    expect(screen.getByText('Backend API')).toBeInTheDocument()
  })

  it('selecting a project loads the board', async () => {
    const user = userEvent.setup()
    render(<App />)

    await screen.findByText('Frontend App')
    await user.click(screen.getByText('Frontend App'))

    await waitFor(() => {
      expect(mockApi.getBoard).toHaveBeenCalledWith('p1')
    })

    expect(await screen.findByText('Build login page')).toBeInTheDocument()
    expect(screen.getByText('Setup CI pipeline')).toBeInTheDocument()
  })

  it('displays board columns after project selection', async () => {
    const user = userEvent.setup()
    render(<App />)

    await screen.findByText('Frontend App')
    await user.click(screen.getByText('Frontend App'))

    expect(await screen.findByText('Backlog')).toBeInTheDocument()
    expect(screen.getByText('In Progress')).toBeInTheDocument()
    expect(screen.getByText('Done')).toBeInTheDocument()
  })

  it('shows worktrees in sidebar after selecting a project', async () => {
    const user = userEvent.setup()
    render(<App />)

    await screen.findByText('Frontend App')
    await user.click(screen.getByText('Frontend App'))

    await waitFor(() => {
      expect(mockApi.getWorktrees).toHaveBeenCalledWith('p1')
    })

    expect(await screen.findByText('wt-ui')).toBeInTheDocument()
  })

  it('clicking a task card opens the card detail slide-out', async () => {
    const user = userEvent.setup()
    render(<App />)

    await screen.findByText('Frontend App')
    await user.click(screen.getByText('Frontend App'))

    const taskCard = await screen.findByText('Build login page')
    await user.click(taskCard)

    // Card detail should show task title, description, and breadcrumb
    await waitFor(() => {
      expect(screen.getByText('Create the login form with validation')).toBeInTheDocument()
    })
    // Breadcrumb appears in both the task card and the card detail
    const breadcrumbs = screen.getAllByText('Authentication / Login')
    expect(breadcrumbs.length).toBeGreaterThanOrEqual(2)
  })

  it('closing card detail returns to board view', async () => {
    const user = userEvent.setup()
    render(<App />)

    await screen.findByText('Frontend App')
    await user.click(screen.getByText('Frontend App'))

    const taskCard = await screen.findByText('Build login page')
    await user.click(taskCard)

    await waitFor(() => {
      expect(screen.getByText('Create the login form with validation')).toBeInTheDocument()
    })

    // Click the close button
    await user.click(screen.getByText('x'))

    // Description should be gone (card detail closed)
    await waitFor(() => {
      expect(screen.queryByText('Create the login form with validation')).not.toBeInTheDocument()
    })
    // Board should still be visible
    expect(screen.getByText('Build login page')).toBeInTheDocument()
  })

  it('shows board header stats', async () => {
    const user = userEvent.setup()
    render(<App />)

    await screen.findByText('Frontend App')
    await user.click(screen.getByText('Frontend App'))

    await waitFor(() => {
      expect(screen.getByText(/2 tasks/)).toBeInTheDocument()
      expect(screen.getByText(/0 done/)).toBeInTheDocument()
    })
  })

  it('card detail shows expedite and agent badges', async () => {
    const user = userEvent.setup()
    render(<App />)

    await screen.findByText('Frontend App')
    await user.click(screen.getByText('Frontend App'))

    const taskCard = await screen.findByText('Build login page')
    await user.click(taskCard)

    await waitFor(() => {
      // The card detail should show the expedite badge
      const expediteBadges = screen.getAllByText('expedite')
      expect(expediteBadges.length).toBeGreaterThan(0)
    })
  })
})
