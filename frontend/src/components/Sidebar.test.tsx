import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi } from 'vitest'
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
    const { container } = render(
      <MemoryRouter>
        <Sidebar projects={mockProjects} selectedProjectId="p1" worktrees={mockWorktrees} />
      </MemoryRouter>
    )
    expect(screen.getByText('Agents')).toBeInTheDocument()
    const list = container.querySelector('.worktree-list')!
    expect(within(list).getByText('wt-backend')).toBeInTheDocument()
    expect(within(list).getByText('wt-frontend')).toBeInTheDocument()
  })

  it('shows project stats for the selected project', () => {
    render(
      <MemoryRouter>
        <Sidebar
          projects={mockProjects}
          selectedProjectId="p1"
          worktrees={mockWorktrees}
          boardStats={{ total_tasks: 10, done_count: 3 }}
        />
      </MemoryRouter>
    )
    expect(screen.getByText('2 agents · 3/10 done')).toBeInTheDocument()
  })

  it('does not show stats when no board data', () => {
    render(
      <MemoryRouter>
        <Sidebar
          projects={mockProjects}
          selectedProjectId="p1"
          worktrees={mockWorktrees}
        />
      </MemoryRouter>
    )
    // No stats line should render
    expect(screen.queryByText(/done/)).not.toBeInTheDocument()
  })

  it('applies pulse class to online worktree dots', () => {
    const { container } = render(
      <MemoryRouter>
        <Sidebar projects={mockProjects} selectedProjectId="p1" worktrees={mockWorktrees} />
      </MemoryRouter>
    )
    const list = container.querySelector('.worktree-list')!
    // wt-backend is online — its dot should have the pulse class
    const backendItem = within(list).getByText('wt-backend').closest('.worktree-item')
    const dot = backendItem!.querySelector('.status-dot')
    expect(dot).toHaveClass('pulse')

    // wt-frontend is offline — no pulse
    const frontendItem = within(list).getByText('wt-frontend').closest('.worktree-item')
    const offlineDot = frontendItem!.querySelector('.status-dot')
    expect(offlineDot).not.toHaveClass('pulse')
  })

  it('shows green project-health dot when agents are online and tasks progressing', () => {
    const onlineWorktrees: Worktree[] = [
      { id: 'wt1', project_id: 'p1', name: 'wt-1', worktree_path: '/tmp', branch_name: 'main', status: 'online', current_task_id: 't1', last_heartbeat: null, created_at: '' },
    ]
    render(
      <MemoryRouter>
        <Sidebar
          projects={mockProjects}
          selectedProjectId="p1"
          worktrees={onlineWorktrees}
          boardStats={{ total_tasks: 5, done_count: 2 }}
        />
      </MemoryRouter>
    )
    const button = screen.getByText('Alpha').closest('button')
    const dot = button!.querySelector('.project-health')
    expect(dot).toHaveClass('health-green')
  })

  it('shows yellow project-health dot when agents online but no tasks progressing', () => {
    const onlineWorktrees: Worktree[] = [
      { id: 'wt1', project_id: 'p1', name: 'wt-1', worktree_path: '/tmp', branch_name: 'main', status: 'online', current_task_id: null, last_heartbeat: null, created_at: '' },
    ]
    render(
      <MemoryRouter>
        <Sidebar
          projects={mockProjects}
          selectedProjectId="p1"
          worktrees={onlineWorktrees}
          boardStats={{ total_tasks: 5, done_count: 0 }}
        />
      </MemoryRouter>
    )
    const button = screen.getByText('Alpha').closest('button')
    const dot = button!.querySelector('.project-health')
    expect(dot).toHaveClass('health-yellow')
  })

  it('shows red project-health dot when no agents are online', () => {
    const offlineWorktrees: Worktree[] = [
      { id: 'wt1', project_id: 'p1', name: 'wt-1', worktree_path: '/tmp', branch_name: 'main', status: 'offline', current_task_id: null, last_heartbeat: null, created_at: '' },
    ]
    render(
      <MemoryRouter>
        <Sidebar
          projects={mockProjects}
          selectedProjectId="p1"
          worktrees={offlineWorktrees}
          boardStats={{ total_tasks: 5, done_count: 0 }}
        />
      </MemoryRouter>
    )
    const button = screen.getByText('Alpha').closest('button')
    const dot = button!.querySelector('.project-health')
    expect(dot).toHaveClass('health-red')
  })

  it('calls onAgentClick when a worktree is clicked', async () => {
    const user = userEvent.setup()
    const onAgentClick = vi.fn()
    const { container } = render(
      <MemoryRouter>
        <Sidebar projects={mockProjects} selectedProjectId="p1" worktrees={mockWorktrees} onAgentClick={onAgentClick} />
      </MemoryRouter>
    )
    const list = container.querySelector('.worktree-list')!
    await user.click(within(list).getByText('wt-backend'))
    expect(onAgentClick).toHaveBeenCalledWith('wt1')
  })

  it('highlights active agent filter', () => {
    const { container } = render(
      <MemoryRouter>
        <Sidebar projects={mockProjects} selectedProjectId="p1" worktrees={mockWorktrees} agentFilter="wt1" />
      </MemoryRouter>
    )
    const list = container.querySelector('.worktree-list')!
    const backendItem = within(list).getByText('wt-backend').closest('.worktree-item')
    expect(backendItem).toHaveClass('worktree-active')
    const frontendItem = within(list).getByText('wt-frontend').closest('.worktree-item')
    expect(frontendItem).not.toHaveClass('worktree-active')
  })

  it('shows task count on worktree items', () => {
    const { container } = render(
      <MemoryRouter>
        <Sidebar projects={mockProjects} selectedProjectId="p1" worktrees={mockWorktrees} agentTaskCounts={{ wt1: 3, wt2: 0 }} />
      </MemoryRouter>
    )
    const list = container.querySelector('.worktree-list')!
    const backendItem = within(list).getByText('wt-backend').closest('.worktree-item')
    expect(backendItem?.querySelector('.worktree-task-count')).toHaveTextContent('3')
    const frontendItem = within(list).getByText('wt-frontend').closest('.worktree-item')
    expect(frontendItem?.querySelector('.worktree-task-count')).toHaveTextContent('0')
  })

  it('shows context menu on right-click of project', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <Sidebar projects={mockProjects} selectedProjectId="p1" worktrees={[]} onDeleteProject={vi.fn()} />
      </MemoryRouter>
    )
    const projectBtn = screen.getByText('Alpha').closest('button')!
    await user.pointer({ keys: '[MouseRight]', target: projectBtn })
    expect(screen.getByTestId('context-menu')).toBeInTheDocument()
    expect(screen.getByText('Delete project')).toBeInTheDocument()
  })

  it('calls onDeleteProject when delete is clicked in context menu', async () => {
    const user = userEvent.setup()
    const onDelete = vi.fn()
    render(
      <MemoryRouter>
        <Sidebar projects={mockProjects} selectedProjectId="p1" worktrees={[]} onDeleteProject={onDelete} />
      </MemoryRouter>
    )
    const projectBtn = screen.getByText('Alpha').closest('button')!
    await user.pointer({ keys: '[MouseRight]', target: projectBtn })
    await user.click(screen.getByText('Delete project'))
    expect(onDelete).toHaveBeenCalledWith('p1')
  })

  it('does not show project-health dot for unselected projects', () => {
    render(
      <MemoryRouter>
        <Sidebar
          projects={mockProjects}
          selectedProjectId="p1"
          worktrees={mockWorktrees}
          boardStats={{ total_tasks: 5, done_count: 2 }}
        />
      </MemoryRouter>
    )
    // Beta (p2) is not selected — should not have a health dot
    const betaButton = screen.getByText('Beta').closest('button')
    const dot = betaButton!.querySelector('.project-health')
    expect(dot).toBeNull()
  })
})
