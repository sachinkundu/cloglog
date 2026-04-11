import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { CardDetail } from './CardDetail'
import { api } from '../api/client'
import type { TaskCard, DocumentSummary, Document } from '../api/types'

vi.mock('../api/client', () => ({
  api: {
    getTaskDocuments: vi.fn(),
    getDocument: vi.fn(),
  },
}))

const mockApi = vi.mocked(api)

const baseTask: TaskCard = {
  id: 't1',
  feature_id: 'f1',
  title: 'Implement auth',
  description: 'Build the auth flow',
  status: 'in_progress',
  priority: 'normal',
  task_type: 'task',
  pr_url: null,
  pr_merged: false,
  worktree_id: null,
  position: 0,
  number: 0,
  archived: false,
  created_at: '',
  updated_at: '',
  epic_title: 'Security',
  feature_title: 'Auth System',
  epic_color: '#7c3aed',
}

const mockDocs: DocumentSummary[] = [
  { id: 'd1', doc_type: 'spec', title: 'Auth Spec', created_at: '' },
  { id: 'd2', doc_type: 'plan', title: 'Auth Plan', created_at: '' },
]

const mockFullDoc: Document = {
  id: 'd1',
  doc_type: 'spec',
  title: 'Auth Spec',
  created_at: '',
  content: 'Spec content goes here',
  source_path: '/docs/spec.md',
  attached_to_type: 'task',
  attached_to_id: 't1',
}

beforeEach(() => {
  vi.clearAllMocks()
  mockApi.getTaskDocuments.mockResolvedValue([])
})

describe('CardDetail', () => {
  it('renders task title and breadcrumb', () => {
    render(<CardDetail task={baseTask} onClose={vi.fn()} />)
    expect(screen.getByText('Implement auth')).toBeInTheDocument()
    expect(screen.getByText('Security / Auth System')).toBeInTheDocument()
  })

  it('renders task description', () => {
    render(<CardDetail task={baseTask} onClose={vi.fn()} />)
    expect(screen.getByText('Build the auth flow')).toBeInTheDocument()
  })

  it('does not render description section when description is empty', () => {
    const noDescTask = { ...baseTask, description: '' }
    render(<CardDetail task={noDescTask} onClose={vi.fn()} />)
    expect(screen.queryByText('Description')).not.toBeInTheDocument()
  })

  it('renders status badge', () => {
    render(<CardDetail task={baseTask} onClose={vi.fn()} />)
    expect(screen.getByText('in_progress')).toBeInTheDocument()
  })

  it('renders expedite badge when priority is expedite', () => {
    const expediteTask = { ...baseTask, priority: 'expedite' }
    render(<CardDetail task={expediteTask} onClose={vi.fn()} />)
    expect(screen.getByText('expedite')).toBeInTheDocument()
  })

  it('does not render expedite badge for normal priority', () => {
    render(<CardDetail task={baseTask} onClose={vi.fn()} />)
    expect(screen.queryByText('expedite')).not.toBeInTheDocument()
  })

  it('calls onClose when close button is clicked', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    render(<CardDetail task={baseTask} onClose={onClose} />)

    await user.click(screen.getByText('x'))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('calls onClose when overlay is clicked', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    render(<CardDetail task={baseTask} onClose={onClose} />)

    // Click the overlay (outermost element)
    const overlay = document.querySelector('.card-detail-overlay')!
    await user.click(overlay)
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('does not call onClose when card content is clicked', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    render(<CardDetail task={baseTask} onClose={onClose} />)

    await user.click(screen.getByText('Implement auth'))
    expect(onClose).not.toHaveBeenCalled()
  })

  it('fetches and renders document chips', async () => {
    mockApi.getTaskDocuments.mockResolvedValue(mockDocs)
    render(<CardDetail task={baseTask} onClose={vi.fn()} />)

    await waitFor(() => {
      expect(screen.getByText('spec: Auth Spec')).toBeInTheDocument()
      expect(screen.getByText('plan: Auth Plan')).toBeInTheDocument()
    })
  })

  it('shows PR link when pr_url is set', () => {
    const task = { ...baseTask, pr_url: 'https://github.com/sachinkundu/cloglog/pull/77', status: 'review' }
    render(<CardDetail task={task} onClose={vi.fn()} />)
    expect(screen.getByText('PR #77')).toBeInTheDocument()
    expect(screen.getByRole('link')).toHaveAttribute('href', 'https://github.com/sachinkundu/cloglog/pull/77')
  })

  it('does not show PR link when pr_url is null', () => {
    render(<CardDetail task={baseTask} onClose={vi.fn()} />)
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  it('shows merged badge in card detail when pr_merged is true', () => {
    const task = { ...baseTask, pr_url: 'https://github.com/sachinkundu/cloglog/pull/77', pr_merged: true, status: 'done' }
    render(<CardDetail task={task} onClose={vi.fn()} />)
    expect(screen.getByText('Merged')).toBeInTheDocument()
  })

  it('loads and displays document content when a doc chip is clicked', async () => {
    const user = userEvent.setup()
    mockApi.getTaskDocuments.mockResolvedValue(mockDocs)
    mockApi.getDocument.mockResolvedValue(mockFullDoc)
    render(<CardDetail task={baseTask} onClose={vi.fn()} />)

    await waitFor(() => {
      expect(screen.getByText('spec: Auth Spec')).toBeInTheDocument()
    })

    await user.click(screen.getByText('spec: Auth Spec'))

    await waitFor(() => {
      expect(screen.getByText('Spec content goes here')).toBeInTheDocument()
    })
    expect(mockApi.getDocument).toHaveBeenCalledWith('d1')
  })
})
