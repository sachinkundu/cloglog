import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import { Column } from './Column'
import type { BoardColumn } from '../api/types'

const makeTask = (id: string, title: string, status: string) => ({
  id,
  feature_id: 'f1',
  title,
  description: '',
  status,
  priority: 'normal',
  worktree_id: null,
  position: 0,
  created_at: '',
  updated_at: '',
  epic_title: 'Epic',
  feature_title: 'Feature',
})

describe('Column', () => {
  it('renders column label for known statuses', () => {
    const column: BoardColumn = { status: 'in_progress', tasks: [] }
    render(<Column column={column} onTaskClick={vi.fn()} />)
    expect(screen.getByText('In Progress')).toBeInTheDocument()
  })

  it('falls back to raw status for unknown statuses', () => {
    const column: BoardColumn = { status: 'custom_status', tasks: [] }
    render(<Column column={column} onTaskClick={vi.fn()} />)
    expect(screen.getByText('custom_status')).toBeInTheDocument()
  })

  it('renders task count', () => {
    const column: BoardColumn = {
      status: 'backlog',
      tasks: [makeTask('t1', 'Task A', 'backlog'), makeTask('t2', 'Task B', 'backlog')],
    }
    render(<Column column={column} onTaskClick={vi.fn()} />)
    expect(screen.getByText('2')).toBeInTheDocument()
  })

  it('renders all tasks', () => {
    const column: BoardColumn = {
      status: 'backlog',
      tasks: [makeTask('t1', 'Task A', 'backlog'), makeTask('t2', 'Task B', 'backlog')],
    }
    render(<Column column={column} onTaskClick={vi.fn()} />)
    expect(screen.getByText('Task A')).toBeInTheDocument()
    expect(screen.getByText('Task B')).toBeInTheDocument()
  })

  it('calls onTaskClick with the correct task id', async () => {
    const user = userEvent.setup()
    const onTaskClick = vi.fn()
    const column: BoardColumn = {
      status: 'backlog',
      tasks: [makeTask('t1', 'Task A', 'backlog')],
    }
    render(<Column column={column} onTaskClick={onTaskClick} />)

    await user.click(screen.getByText('Task A'))
    expect(onTaskClick).toHaveBeenCalledWith('t1')
  })

  it('renders empty column with zero count', () => {
    const column: BoardColumn = { status: 'done', tasks: [] }
    render(<Column column={column} onTaskClick={vi.fn()} />)
    expect(screen.getByText('Done')).toBeInTheDocument()
    expect(screen.getByText('0')).toBeInTheDocument()
  })
})
