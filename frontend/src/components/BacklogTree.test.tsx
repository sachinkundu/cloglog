import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import { BacklogTree } from './BacklogTree'
import type { BacklogEpic } from '../api/types'

const mockBacklog: BacklogEpic[] = [
  {
    epic: {
      id: 'e1',
      project_id: 'p1',
      title: 'Auth System',
      description: '',
      bounded_context: '',
      context_description: '',
      status: 'in_progress',
      position: 0,
      created_at: '',
      color: '#7c3aed',
    },
    features: [
      {
        feature: {
          id: 'f1',
          epic_id: 'e1',
          title: 'OAuth',
          description: '',
          status: 'planned',
          position: 0,
          created_at: '',
        },
        tasks: [
          { id: 't1', title: 'Callback handler', status: 'backlog', priority: 'normal' },
          { id: 't2', title: 'Token refresh', status: 'backlog', priority: 'expedite' },
        ],
        task_counts: { total: 2, done: 0 },
      },
    ],
    task_counts: { total: 2, done: 0 },
  },
]

describe('BacklogTree', () => {
  it('renders epic headers', () => {
    render(<BacklogTree backlog={mockBacklog} onItemClick={vi.fn()} />)
    expect(screen.getByText('Auth System')).toBeInTheDocument()
  })

  it('shows task count on epic header', () => {
    render(<BacklogTree backlog={mockBacklog} onItemClick={vi.fn()} />)
    expect(screen.getAllByText('0/2').length).toBeGreaterThanOrEqual(1)
  })

  it('shows features when epic is expanded (default)', () => {
    render(<BacklogTree backlog={mockBacklog} onItemClick={vi.fn()} />)
    expect(screen.getByText('OAuth')).toBeInTheDocument()
  })

  it('shows tasks when feature is expanded (default)', () => {
    render(<BacklogTree backlog={mockBacklog} onItemClick={vi.fn()} />)
    expect(screen.getByText('Callback handler')).toBeInTheDocument()
    expect(screen.getByText('Token refresh')).toBeInTheDocument()
  })

  it('calls onItemClick with epic when epic title is clicked', async () => {
    const user = userEvent.setup()
    const onClick = vi.fn()
    render(<BacklogTree backlog={mockBacklog} onItemClick={onClick} />)
    await user.click(screen.getByText('Auth System'))
    expect(onClick).toHaveBeenCalledWith('epic', 'e1')
  })

  it('calls onItemClick with task when task is clicked', async () => {
    const user = userEvent.setup()
    const onClick = vi.fn()
    render(<BacklogTree backlog={mockBacklog} onItemClick={onClick} />)
    await user.click(screen.getByText('Callback handler'))
    expect(onClick).toHaveBeenCalledWith('task', 't1')
  })
})
