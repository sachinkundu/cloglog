import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect } from 'vitest'
import { Layout } from './Layout'
import type { Project, Worktree } from '../api/types'

const projects: Project[] = [
  { id: 'p1', name: 'Alpha', description: '', repo_url: '', status: 'active', created_at: '' },
]

const worktrees: Worktree[] = [
  { id: 'wt1', project_id: 'p1', name: 'wt-api', worktree_path: '/tmp', branch_name: 'main', status: 'online', current_task_id: null, last_heartbeat: null, created_at: '2024-01-01T00:00:00Z' },
]

describe('Layout', () => {
  it('renders sidebar with projects', () => {
    render(
      <MemoryRouter>
        <Layout projects={projects} selectedProjectId={null} worktrees={[]}>
          <div>content</div>
        </Layout>
      </MemoryRouter>
    )
    expect(screen.getByText('Alpha')).toBeInTheDocument()
  })

  it('renders children in main content area', () => {
    render(
      <MemoryRouter>
        <Layout projects={projects} selectedProjectId={null} worktrees={[]}>
          <div>My board content</div>
        </Layout>
      </MemoryRouter>
    )
    expect(screen.getByText('My board content')).toBeInTheDocument()
  })

  it('renders theme toggle', () => {
    render(
      <MemoryRouter>
        <Layout projects={projects} selectedProjectId={null} worktrees={worktrees}>
          <div>content</div>
        </Layout>
      </MemoryRouter>
    )
    expect(screen.getByRole('button', { name: 'Toggle theme' })).toBeInTheDocument()
  })
})
