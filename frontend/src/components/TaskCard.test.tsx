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
  task_type: 'task',
  pr_url: null,
  worktree_id: null,
  position: 0,
  number: 1,
  archived: false,
  created_at: '',
  updated_at: '',
  epic_title: 'Auth',
  feature_title: 'User Login',
  epic_color: '#7c3aed',
}

describe('TaskCard', () => {
  it('renders task title and breadcrumb pills', () => {
    render(<TaskCard task={baseTask} onClick={vi.fn()} />)
    expect(screen.getByText('Implement login')).toBeInTheDocument()
    expect(screen.getByText('Auth')).toBeInTheDocument()
    expect(screen.getByText('User Login')).toBeInTheDocument()
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

  it('renders breadcrumb pills with epic color', () => {
    render(<TaskCard task={{ ...baseTask, epic_title: 'Auth', feature_title: 'OAuth', epic_color: '#7c3aed' }} onClick={vi.fn()} />)
    expect(screen.getByText('Auth')).toBeInTheDocument()
    expect(screen.getByText('OAuth')).toBeInTheDocument()
  })

  it('renders expedite priority badge', () => {
    render(<TaskCard task={{ ...baseTask, priority: 'expedite' }} onClick={vi.fn()} />)
    expect(screen.getByText('expedite')).toBeInTheDocument()
  })

  it('shows PR link when pr_url is set', () => {
    const task = { ...baseTask, pr_url: 'https://github.com/sachinkundu/cloglog/pull/45' }
    render(<TaskCard task={task} onClick={vi.fn()} />)
    expect(screen.getByText('PR #45')).toBeInTheDocument()
    expect(screen.getByRole('link')).toHaveAttribute('href', 'https://github.com/sachinkundu/cloglog/pull/45')
  })

  it('does not show PR link when pr_url is null', () => {
    render(<TaskCard task={baseTask} onClick={vi.fn()} />)
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  it('PR link click does not trigger card onClick', async () => {
    const user = userEvent.setup()
    const onClick = vi.fn()
    const task = { ...baseTask, pr_url: 'https://github.com/sachinkundu/cloglog/pull/10' }
    render(<TaskCard task={task} onClick={onClick} />)
    await user.click(screen.getByRole('link'))
    expect(onClick).not.toHaveBeenCalled()
  })
})
