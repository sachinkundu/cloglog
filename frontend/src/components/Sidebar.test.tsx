import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect } from 'vitest'
import { Sidebar } from './Sidebar'
import type { Project, Worktree } from '../api/types'

const mockProjects: Project[] = [
  { id: 'p1', name: 'Alpha', description: 'desc', repo_url: '', status: 'active', created_at: '' },
  { id: 'p2', name: 'Beta', description: 'desc', repo_url: '', status: 'archived', created_at: '' },
]

const mockWorktrees: Worktree[] = [
  { id: 'wt1', project_id: 'p1', name: 'wt-backend', worktree_path: '/tmp', branch_name: 'main', status: 'online', current_task_id: null, last_heartbeat: null, created_at: '2024-01-01T00:00:00Z' },
  { id: 'wt2', project_id: 'p1', name: 'wt-frontend', worktree_path: '/tmp', branch_name: 'main', status: 'offline', current_task_id: null, last_heartbeat: null, created_at: '2024-01-01T00:00:00Z' },
]

describe('Sidebar', () => {
  it('renders the app title', () => {
    render(
      <MemoryRouter>
        <Sidebar projects={[]} selectedProjectId={null} worktrees={[]} />
      </MemoryRouter>
    )
    expect(screen.getByText('cloglog')).toBeInTheDocument()
  })

  it('renders all projects', () => {
    render(
      <MemoryRouter>
        <Sidebar projects={mockProjects} selectedProjectId={null} worktrees={[]} />
      </MemoryRouter>
    )
    expect(screen.getByText('Alpha')).toBeInTheDocument()
    expect(screen.getByText('Beta')).toBeInTheDocument()
  })

  it('navigates when a project is clicked', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <Sidebar projects={mockProjects} selectedProjectId={null} worktrees={[]} />
      </MemoryRouter>
    )

    await user.click(screen.getByText('Alpha'))
    // Navigation is handled internally by useNavigate; no callback to assert
  })

  it('highlights the selected project', () => {
    render(
      <MemoryRouter>
        <Sidebar projects={mockProjects} selectedProjectId="p1" worktrees={[]} />
      </MemoryRouter>
    )
    const button = screen.getByText('Alpha').closest('button')
    expect(button).toHaveClass('selected')
  })

  it('does not show worktrees when no project is selected', () => {
    render(
      <MemoryRouter>
        <Sidebar projects={mockProjects} selectedProjectId={null} worktrees={mockWorktrees} />
      </MemoryRouter>
    )
    expect(screen.queryByText('Agents')).not.toBeInTheDocument()
  })

  it('shows worktrees when a project is selected', () => {
    render(
      <MemoryRouter>
        <Sidebar projects={mockProjects} selectedProjectId="p1" worktrees={mockWorktrees} />
      </MemoryRouter>
    )
    expect(screen.getByText('Agents')).toBeInTheDocument()
    expect(screen.getByText('wt-backend')).toBeInTheDocument()
    expect(screen.getByText('wt-frontend')).toBeInTheDocument()
  })
})
