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
  number: 1,
  created_at: '',
  updated_at: '',
  epic_title: 'Epic',
  feature_title: 'Feature',
  epic_color: '#7c3aed',
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

  it('shows Archive button only for done column with tasks', () => {
    const column: BoardColumn = {
      status: 'done',
      tasks: [makeTask('t1', 'Done Task', 'done')],
    }
    render(<Column column={column} onTaskClick={vi.fn()} />)
    expect(screen.getByText('Archive')).toBeInTheDocument()
  })

  it('does not show Archive button for non-done columns', () => {
    const column: BoardColumn = {
      status: 'in_progress',
      tasks: [makeTask('t1', 'Task', 'in_progress')],
    }
    render(<Column column={column} onTaskClick={vi.fn()} />)
    expect(screen.queryByText('Archive')).not.toBeInTheDocument()
  })

  it('archives done tasks and shows collapsed archived section', async () => {
    const user = userEvent.setup()
    const column: BoardColumn = {
      status: 'done',
      tasks: [makeTask('t1', 'Done Task', 'done')],
    }
    render(<Column column={column} onTaskClick={vi.fn()} />)

    await user.click(screen.getByText('Archive'))
    // Task should be hidden from main list
    expect(screen.queryByText('Done Task')).not.toBeInTheDocument()
    // Archived section should appear
    expect(screen.getByText('Archived (1)')).toBeInTheDocument()
  })

  it('expands archived section to show strikethrough tasks', async () => {
    const user = userEvent.setup()
    const column: BoardColumn = {
      status: 'done',
      tasks: [makeTask('t1', 'Done Task', 'done')],
    }
    render(<Column column={column} onTaskClick={vi.fn()} />)

    await user.click(screen.getByText('Archive'))
    await user.click(screen.getByText('Archived (1)'))
    // Task should now be visible again in archived section
    expect(screen.getByText('Done Task')).toBeInTheDocument()
  })
})
