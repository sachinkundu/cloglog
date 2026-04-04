import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
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
      <Layout projects={projects} selectedProjectId={null} onSelectProject={vi.fn()} worktrees={[]}>
        <div>content</div>
      </Layout>
    )
    expect(screen.getByText('Alpha')).toBeInTheDocument()
  })

  it('renders children in main content area', () => {
    render(
      <Layout projects={projects} selectedProjectId={null} onSelectProject={vi.fn()} worktrees={[]}>
        <div>My board content</div>
      </Layout>
    )
    expect(screen.getByText('My board content')).toBeInTheDocument()
  })

  it('renders theme toggle', () => {
    render(
      <Layout projects={projects} selectedProjectId={null} onSelectProject={vi.fn()} worktrees={worktrees}>
        <div>content</div>
      </Layout>
    )
    expect(screen.getByRole('button', { name: 'Toggle theme' })).toBeInTheDocument()
  })
})
