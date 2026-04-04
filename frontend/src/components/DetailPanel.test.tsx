import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import { DetailPanel } from './DetailPanel'

describe('DetailPanel', () => {
  it('renders epic detail', () => {
    render(
      <DetailPanel
        type="epic"
        data={{
          title: 'Auth System',
          description: 'Authentication epic',
          color: '#7c3aed',
          bounded_context: 'Agent',
          task_counts: { total: 8, done: 2 },
          number: 1,
          features: [
            { title: 'OAuth', task_counts: { total: 3, done: 1 } },
            { title: 'Session', task_counts: { total: 5, done: 1 } },
          ],
        }}
        onClose={vi.fn()}
        onNavigate={vi.fn()}
      />
    )
    expect(screen.getByText('Auth System')).toBeInTheDocument()
    expect(screen.getByText('Authentication epic')).toBeInTheDocument()
    expect(screen.getByText('OAuth')).toBeInTheDocument()
    expect(screen.getByText('Session')).toBeInTheDocument()
  })

  it('renders feature detail with parent epic pill', () => {
    render(
      <DetailPanel
        type="feature"
        data={{
          title: 'OAuth Provider',
          description: 'OAuth implementation',
          epic: { title: 'Auth System', id: 'e1', color: '#7c3aed' },
          task_counts: { total: 3, done: 1 },
          number: 2,
          tasks: [
            { id: 't1', title: 'Callback', status: 'done' },
            { id: 't2', title: 'Token refresh', status: 'backlog' },
          ],
        }}
        onClose={vi.fn()}
        onNavigate={vi.fn()}
      />
    )
    expect(screen.getByText('OAuth Provider')).toBeInTheDocument()
    expect(screen.getByText('Auth System')).toBeInTheDocument()
    expect(screen.getByText('Callback')).toBeInTheDocument()
  })

  it('renders task detail with breadcrumb pills', () => {
    render(
      <DetailPanel
        type="task"
        data={{
          title: 'Add callback handler',
          description: 'Implement the OAuth callback',
          status: 'in_progress',
          priority: 'normal',
          epic: { title: 'Auth System', id: 'e1', color: '#7c3aed' },
          feature: { title: 'OAuth', id: 'f1' },
          worktree_id: null,
          number: 37,
        }}
        onClose={vi.fn()}
        onNavigate={vi.fn()}
      />
    )
    expect(screen.getByText('Add callback handler')).toBeInTheDocument()
    expect(screen.getByText('Auth System')).toBeInTheDocument()
    expect(screen.getByText('OAuth')).toBeInTheDocument()
  })

  it('calls onClose when overlay is clicked', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    render(
      <DetailPanel
        type="epic"
        data={{
          title: 'Test',
          description: '',
          color: '#000',
          bounded_context: '',
          task_counts: { total: 0, done: 0 },
          features: [],
        }}
        onClose={onClose}
        onNavigate={vi.fn()}
      />
    )
    await user.click(screen.getByTestId('detail-overlay'))
    expect(onClose).toHaveBeenCalled()
  })

  it('calls onNavigate when epic pill is clicked in task detail', async () => {
    const user = userEvent.setup()
    const onNavigate = vi.fn()
    render(
      <DetailPanel
        type="task"
        data={{
          title: 'Task',
          description: '',
          status: 'backlog',
          priority: 'normal',
          epic: { title: 'Auth', id: 'e1', color: '#7c3aed' },
          feature: { title: 'OAuth', id: 'f1' },
          worktree_id: null,
        }}
        onClose={vi.fn()}
        onNavigate={onNavigate}
      />
    )
    await user.click(screen.getByText('Auth'))
    expect(onNavigate).toHaveBeenCalledWith('epic', 'e1')
  })
})
