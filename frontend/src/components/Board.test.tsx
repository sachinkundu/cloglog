import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi } from 'vitest'
import { Board } from './Board'
import type { BoardResponse } from '../api/types'

vi.mock('../hooks/useSearch', () => ({
  useSearch: () => ({ results: [], loading: false, search: vi.fn(), clear: vi.fn() }),
}))

const mockBoard: BoardResponse = {
  project_id: 'p1',
  project_name: 'Test Project',
  columns: [
    {
      status: 'backlog',
      tasks: [
        {
          id: 't1',
          feature_id: 'f1',
          title: 'Task One',
          description: 'First task',
          status: 'backlog',
          priority: 'normal',
          worktree_id: null,
          position: 0,
          created_at: '',
          updated_at: '',
          epic_title: 'Epic A',
          feature_title: 'Feature A',
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
          title: 'Task Two',
          description: 'Second task',
          status: 'in_progress',
          priority: 'expedite',
          worktree_id: 'wt1',
          position: 0,
          created_at: '',
          updated_at: '',
          epic_title: 'Epic B',
          feature_title: 'Feature B',
          epic_color: '#2563eb',
        },
      ],
    },
    {
      status: 'done',
      tasks: [],
    },
  ],
  total_tasks: 2,
  done_count: 0,
}

function renderBoard(overrides?: Partial<Parameters<typeof Board>[0]>) {
  const props = {
    board: mockBoard,
    backlog: [] as never[],
    projectId: 'p1',
    onTaskClick: vi.fn(),
    onItemClick: vi.fn(),
    ...overrides,
  }
  return render(
    <MemoryRouter initialEntries={['/projects/p1']}>
      <Board {...props} />
    </MemoryRouter>
  )
}

describe('Board', () => {
  it('renders the board header with project name', () => {
    renderBoard()
    expect(screen.getByText('Test Project')).toBeInTheDocument()
  })

  it('renders backlog column and flow columns', () => {
    renderBoard()
    expect(screen.getByText('Backlog')).toBeInTheDocument()
    expect(screen.getByText('In Progress')).toBeInTheDocument()
    expect(screen.getByText('Done')).toBeInTheDocument()
  })

  it('renders flow column tasks (not backlog tasks as cards)', () => {
    renderBoard()
    // Task Two is in in_progress column, should render as a card
    expect(screen.getByText('Task Two')).toBeInTheDocument()
  })

  it('calls onTaskClick when a flow column task card is clicked', async () => {
    const user = userEvent.setup()
    const onTaskClick = vi.fn()
    renderBoard({ onTaskClick })

    await user.click(screen.getByText('Task Two'))
    expect(onTaskClick).toHaveBeenCalledWith('t2')
  })

  it('displays task stats in header', () => {
    renderBoard()
    expect(screen.getByText(/2 tasks/)).toBeInTheDocument()
    expect(screen.getByText(/0 done/)).toBeInTheDocument()
  })

  it('shows backlog task count from board data', () => {
    renderBoard()
    // The backlog column should exist with its count
    const backlogSection = document.querySelector('.board-backlog')
    expect(backlogSection).toBeTruthy()
    const countEl = backlogSection!.querySelector('.column-count')
    expect(countEl?.textContent).toBe('1')
  })

  it('renders search widget in header', () => {
    renderBoard()
    expect(screen.getByPlaceholderText('Search epics, features, tasks...')).toBeInTheDocument()
  })
})
