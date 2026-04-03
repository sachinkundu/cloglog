import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import { Sidebar } from './Sidebar'
import type { Project, Worktree } from '../api/types'

const mockProjects: Project[] = [
  { id: 'p1', name: 'Alpha', description: 'desc', repo_url: '', status: 'active', created_at: '' },
  { id: 'p2', name: 'Beta', description: 'desc', repo_url: '', status: 'archived', created_at: '' },
]

const mockWorktrees: Worktree[] = [
  { id: 'wt1', name: 'wt-backend', worktree_path: '/tmp', status: 'active', current_task_id: null, last_heartbeat: '' },
  { id: 'wt2', name: 'wt-frontend', worktree_path: '/tmp', status: 'idle', current_task_id: null, last_heartbeat: '' },
]

describe('Sidebar', () => {
  it('renders the app title', () => {
    render(<Sidebar projects={[]} selectedProjectId={null} onSelectProject={vi.fn()} worktrees={[]} />)
    expect(screen.getByText('cloglog')).toBeInTheDocument()
  })

  it('renders all projects', () => {
    render(<Sidebar projects={mockProjects} selectedProjectId={null} onSelectProject={vi.fn()} worktrees={[]} />)
    expect(screen.getByText('Alpha')).toBeInTheDocument()
    expect(screen.getByText('Beta')).toBeInTheDocument()
  })

  it('calls onSelectProject when a project is clicked', async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    render(<Sidebar projects={mockProjects} selectedProjectId={null} onSelectProject={onSelect} worktrees={[]} />)

    await user.click(screen.getByText('Alpha'))
    expect(onSelect).toHaveBeenCalledWith('p1')
  })

  it('highlights the selected project', () => {
    render(<Sidebar projects={mockProjects} selectedProjectId="p1" onSelectProject={vi.fn()} worktrees={[]} />)
    const button = screen.getByText('Alpha').closest('button')
    expect(button).toHaveClass('selected')
  })

  it('does not show worktrees when no project is selected', () => {
    render(<Sidebar projects={mockProjects} selectedProjectId={null} onSelectProject={vi.fn()} worktrees={mockWorktrees} />)
    expect(screen.queryByText('Agents')).not.toBeInTheDocument()
  })

  it('shows worktrees when a project is selected', () => {
    render(<Sidebar projects={mockProjects} selectedProjectId="p1" onSelectProject={vi.fn()} worktrees={mockWorktrees} />)
    expect(screen.getByText('Agents')).toBeInTheDocument()
    expect(screen.getByText('wt-backend')).toBeInTheDocument()
    expect(screen.getByText('wt-frontend')).toBeInTheDocument()
  })
})
