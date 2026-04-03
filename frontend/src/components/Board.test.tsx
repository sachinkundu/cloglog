import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import { Board } from './Board'
import type { BoardResponse } from '../api/types'

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

describe('Board', () => {
  it('renders the board header with project name', () => {
    render(<Board board={mockBoard} onTaskClick={vi.fn()} />)
    expect(screen.getByText('Test Project')).toBeInTheDocument()
  })

  it('renders all columns', () => {
    render(<Board board={mockBoard} onTaskClick={vi.fn()} />)
    expect(screen.getByText('Backlog')).toBeInTheDocument()
    expect(screen.getByText('In Progress')).toBeInTheDocument()
    expect(screen.getByText('Done')).toBeInTheDocument()
  })

  it('renders tasks inside their columns', () => {
    render(<Board board={mockBoard} onTaskClick={vi.fn()} />)
    expect(screen.getByText('Task One')).toBeInTheDocument()
    expect(screen.getByText('Task Two')).toBeInTheDocument()
  })

  it('calls onTaskClick when a task card is clicked', async () => {
    const user = userEvent.setup()
    const onTaskClick = vi.fn()
    render(<Board board={mockBoard} onTaskClick={onTaskClick} />)

    await user.click(screen.getByText('Task One'))
    expect(onTaskClick).toHaveBeenCalledWith('t1')
  })

  it('displays task stats in header', () => {
    render(<Board board={mockBoard} onTaskClick={vi.fn()} />)
    expect(screen.getByText(/2 tasks/)).toBeInTheDocument()
    expect(screen.getByText(/0 done/)).toBeInTheDocument()
  })
})
