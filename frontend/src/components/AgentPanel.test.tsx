import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { AgentPanel } from './AgentPanel'
import type { Worktree } from '../api/types'

const mockWorktrees: Worktree[] = [
  { id: 'wt1', project_id: 'p1', name: 'wt-backend', worktree_path: '/tmp/wt-backend', branch_name: 'feat-api', status: 'online', current_task_id: 't1', last_heartbeat: new Date().toISOString(), created_at: '2024-01-01T00:00:00Z' },
  { id: 'wt2', project_id: 'p1', name: 'wt-frontend', worktree_path: '/tmp/wt-frontend', branch_name: 'feat-ui', status: 'offline', current_task_id: null, last_heartbeat: null, created_at: '2024-01-01T00:00:00Z' },
]

describe('AgentPanel', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('renders manage agents title', () => {
    render(<AgentPanel worktrees={mockWorktrees} projectId="p1" />)
    expect(screen.getByText('Manage Agents')).toBeInTheDocument()
  })

  it('renders all worktree names', () => {
    render(<AgentPanel worktrees={mockWorktrees} projectId="p1" />)
    expect(screen.getByText('wt-backend')).toBeInTheDocument()
    expect(screen.getByText('wt-frontend')).toBeInTheDocument()
  })

  it('expands agent details on click', async () => {
    const user = userEvent.setup()
    render(<AgentPanel worktrees={mockWorktrees} projectId="p1" />)
    await user.click(screen.getByText('wt-backend'))
    expect(screen.getByText('feat-api')).toBeInTheDocument()
    expect(screen.getByText('Request Shutdown')).toBeInTheDocument()
  })

  it('does not show shutdown button for offline agents', async () => {
    const user = userEvent.setup()
    render(<AgentPanel worktrees={mockWorktrees} projectId="p1" />)
    await user.click(screen.getByText('wt-frontend'))
    expect(screen.getByText('feat-ui')).toBeInTheDocument()
    expect(screen.queryByText('Request Shutdown')).not.toBeInTheDocument()
  })

  it('calls API on shutdown button click', async () => {
    const user = userEvent.setup()
    const { api } = await import('../api/client')
    const spy = vi.spyOn(api, 'requestWorktreeShutdown').mockResolvedValue({ shutdown_requested: true })
    const onRefresh = vi.fn()
    render(<AgentPanel worktrees={mockWorktrees} projectId="p1" onRefresh={onRefresh} />)
    await user.click(screen.getByText('wt-backend'))
    await user.click(screen.getByText('Request Shutdown'))
    expect(spy).toHaveBeenCalledWith('p1', 'wt1')
    expect(onRefresh).toHaveBeenCalled()
    spy.mockRestore()
  })

  it('returns null when no worktrees', () => {
    const { container } = render(<AgentPanel worktrees={[]} projectId="p1" />)
    expect(container.querySelector('.agent-panel')).toBeNull()
  })

  it('collapses details on second click', async () => {
    const user = userEvent.setup()
    render(<AgentPanel worktrees={mockWorktrees} projectId="p1" />)
    await user.click(screen.getByText('wt-backend'))
    expect(screen.getByText('feat-api')).toBeInTheDocument()
    await user.click(screen.getByText('wt-backend'))
    expect(screen.queryByText('feat-api')).not.toBeInTheDocument()
  })

  it('shows task counts from agentTaskCounts', async () => {
    const user = userEvent.setup()
    render(<AgentPanel worktrees={mockWorktrees} projectId="p1" agentTaskCounts={{ wt1: 3, wt2: 0 }} />)
    await user.click(screen.getByText('wt-backend'))
    // Tasks row shows the count
    const rows = screen.getAllByText('3')
    expect(rows.length).toBeGreaterThanOrEqual(1)
  })
})
