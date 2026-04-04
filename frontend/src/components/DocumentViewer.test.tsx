import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import { DocumentViewer } from './DocumentViewer'

describe('DocumentViewer', () => {
  it('fetches and renders document content as markdown', async () => {
    const { api } = await import('../api/client')
    vi.spyOn(api, 'getDocument').mockResolvedValue({
      id: 'd1',
      doc_type: 'spec',
      title: 'Auth Spec',
      content: '# Authentication\n\nThis is the **auth** spec.',
      source_path: '',
      attached_to_type: 'feature',
      attached_to_id: 'f1',
      created_at: '',
    })

    render(<DocumentViewer documentId="d1" onClose={vi.fn()} />)

    await waitFor(() => {
      expect(screen.getByText('Auth Spec')).toBeInTheDocument()
    })
    // Markdown rendered: h1 becomes a heading, bold becomes strong
    expect(screen.getByText('Authentication')).toBeInTheDocument()
    vi.restoreAllMocks()
  })

  it('calls onClose when overlay is clicked', async () => {
    const { api } = await import('../api/client')
    vi.spyOn(api, 'getDocument').mockResolvedValue({
      id: 'd1',
      doc_type: 'spec',
      title: 'Test',
      content: 'content',
      source_path: '',
      attached_to_type: 'task',
      attached_to_id: 't1',
      created_at: '',
    })

    const user = userEvent.setup()
    const onClose = vi.fn()
    render(<DocumentViewer documentId="d1" onClose={onClose} />)

    await waitFor(() => {
      expect(screen.getByText('Test')).toBeInTheDocument()
    })
    // Click the overlay (not the content)
    await user.click(screen.getByText('Test').closest('.doc-viewer-overlay')!)
    expect(onClose).toHaveBeenCalled()
    vi.restoreAllMocks()
  })

  it('shows error state on fetch failure', async () => {
    const { api } = await import('../api/client')
    vi.spyOn(api, 'getDocument').mockRejectedValue(new Error('fail'))

    render(<DocumentViewer documentId="bad" onClose={vi.fn()} />)

    await waitFor(() => {
      expect(screen.getByText('Failed to load document')).toBeInTheDocument()
    })
    vi.restoreAllMocks()
  })
})
