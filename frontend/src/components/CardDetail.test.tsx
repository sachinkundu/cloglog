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
  worktree_id: null,
  position: 0,
  created_at: '',
  updated_at: '',
  epic_title: 'Security',
  feature_title: 'Auth System',
}

const mockDocs: DocumentSummary[] = [
  { id: 'd1', type: 'spec', title: 'Auth Spec', created_at: '' },
  { id: 'd2', type: 'plan', title: 'Auth Plan', created_at: '' },
]

const mockFullDoc: Document = {
  id: 'd1',
  type: 'spec',
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
