import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import { TaskCard } from './TaskCard'
import type { TaskCard as TaskCardType } from '../api/types'

const baseTask: TaskCardType = {
  id: 't1',
  feature_id: 'f1',
  title: 'Implement login',
  description: 'Add login form',
  status: 'in_progress',
  priority: 'normal',
  worktree_id: null,
  position: 0,
  created_at: '',
  updated_at: '',
  epic_title: 'Auth',
  feature_title: 'User Login',
}

describe('TaskCard', () => {
  it('renders task title and breadcrumb', () => {
    render(<TaskCard task={baseTask} onClick={vi.fn()} />)
    expect(screen.getByText('Implement login')).toBeInTheDocument()
    expect(screen.getByText('Auth / User Login')).toBeInTheDocument()
  })

  it('calls onClick when clicked', async () => {
    const user = userEvent.setup()
    const onClick = vi.fn()
    render(<TaskCard task={baseTask} onClick={onClick} />)

    await user.click(screen.getByText('Implement login'))
    expect(onClick).toHaveBeenCalledOnce()
  })

  it('shows expedite badge when priority is expedite', () => {
    const expediteTask = { ...baseTask, priority: 'expedite' }
    render(<TaskCard task={expediteTask} onClick={vi.fn()} />)
    expect(screen.getByText('expedite')).toBeInTheDocument()
  })

  it('does not show expedite badge for normal priority', () => {
    render(<TaskCard task={baseTask} onClick={vi.fn()} />)
    expect(screen.queryByText('expedite')).not.toBeInTheDocument()
  })

  it('shows agent assigned badge when worktree_id is set', () => {
    const assignedTask = { ...baseTask, worktree_id: 'wt1' }
    render(<TaskCard task={assignedTask} onClick={vi.fn()} />)
    expect(screen.getByText('agent assigned')).toBeInTheDocument()
  })

  it('does not show agent assigned badge when no worktree', () => {
    render(<TaskCard task={baseTask} onClick={vi.fn()} />)
    expect(screen.queryByText('agent assigned')).not.toBeInTheDocument()
  })
})
