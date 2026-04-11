import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, it, expect, vi } from 'vitest'
import { BacklogTree } from './BacklogTree'
import type { BacklogEpic } from '../api/types'

const mockBacklog: BacklogEpic[] = [
  {
    epic: {
      id: 'e1',
      project_id: 'p1',
      title: 'Auth System',
      description: '',
      bounded_context: '',
      context_description: '',
      status: 'in_progress',
      position: 0,
      created_at: '',
      color: '#7c3aed',
      number: 1,
    },
    features: [
      {
        feature: {
          id: 'f1',
          epic_id: 'e1',
          title: 'OAuth',
          description: '',
          status: 'planned',
          position: 0,
          created_at: '',
          number: 1,
        },
        tasks: [
          { id: 't1', title: 'Callback handler', status: 'backlog', priority: 'normal', number: 1 },
          { id: 't2', title: 'Token refresh', status: 'backlog', priority: 'expedite', number: 2 },
        ],
        task_counts: { total: 2, done: 0 },
      },
    ],
    task_counts: { total: 2, done: 0 },
  },
]

const mockWithMixedStatuses: BacklogEpic[] = [
  {
    epic: {
      id: 'e1',
      project_id: 'p1',
      title: 'Auth System',
      description: '',
      bounded_context: '',
      context_description: '',
      status: 'in_progress',
      position: 0,
      created_at: '',
      color: '#7c3aed',
      number: 2,
    },
    features: [
      {
        feature: {
          id: 'f1',
          epic_id: 'e1',
          title: 'OAuth',
          description: '',
          status: 'in_progress',
          position: 0,
          created_at: '',
          number: 2,
        },
        tasks: [
          { id: 't1', title: 'Callback handler', status: 'done', priority: 'normal', number: 3 },
          { id: 't2', title: 'Token refresh', status: 'in_progress', priority: 'normal', number: 4 },
          { id: 't3', title: 'Session persistence', status: 'backlog', priority: 'normal', number: 5 },
        ],
        task_counts: { total: 3, done: 1 },
      },
    ],
    task_counts: { total: 3, done: 1 },
  },
]

describe('BacklogTree', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('renders epic headers', () => {
    render(<BacklogTree backlog={mockBacklog} onItemClick={vi.fn()} />)
    expect(screen.getByText('Auth System')).toBeInTheDocument()
  })

  it('renders segmented progress bar', () => {
    const { container } = render(<BacklogTree backlog={mockBacklog} onItemClick={vi.fn()} />)
    expect(container.querySelectorAll('.seg-progress').length).toBeGreaterThanOrEqual(1)
  })

  it('shows features when epic is expanded (default)', () => {
    render(<BacklogTree backlog={mockBacklog} onItemClick={vi.fn()} />)
    expect(screen.getByText('OAuth')).toBeInTheDocument()
  })

  it('only shows backlog tasks in the tree', () => {
    render(<BacklogTree backlog={mockWithMixedStatuses} onItemClick={vi.fn()} />)
    // Only the backlog task should appear in the tree
    expect(screen.getByText('Session persistence')).toBeInTheDocument()
    // Done and in_progress tasks should NOT appear in the tree
    expect(screen.queryByText('Callback handler')).not.toBeInTheDocument()
    expect(screen.queryByText('Token refresh')).not.toBeInTheDocument()
  })

  it('calls onItemClick with epic when epic title is clicked', async () => {
    const user = userEvent.setup()
    const onClick = vi.fn()
    render(<BacklogTree backlog={mockBacklog} onItemClick={onClick} />)
    await user.click(screen.getByText('Auth System'))
    expect(onClick).toHaveBeenCalledWith('epic', 'e1')
  })

  it('calls onItemClick with task when task is clicked', async () => {
    const user = userEvent.setup()
    const onClick = vi.fn()
    render(<BacklogTree backlog={mockBacklog} onItemClick={onClick} />)
    await user.click(screen.getByText('Callback handler'))
    expect(onClick).toHaveBeenCalledWith('task', 't1')
  })

  it('hides fully completed epics by default', () => {
    const backlogWithDone: BacklogEpic[] = [
      ...mockBacklog,
      {
        epic: {
          id: 'e2', project_id: 'p1', title: 'Done Epic', description: '',
          bounded_context: '', context_description: '', status: 'done',
          position: 1, created_at: '', color: '#10b981', number: 3,
        },
        features: [{
          feature: {
            id: 'f2', epic_id: 'e2', title: 'Done Feature', description: '',
            status: 'done', position: 0, created_at: '', number: 3,
          },
          tasks: [
            { id: 't3', title: 'Done task', status: 'done', priority: 'normal', number: 6 },
          ],
          task_counts: { total: 1, done: 1 },
        }],
        task_counts: { total: 1, done: 1 },
      },
    ]
    render(<BacklogTree backlog={backlogWithDone} onItemClick={vi.fn()} />)
    expect(screen.getByText('Auth System')).toBeInTheDocument()
    expect(screen.queryByText('Done Epic')).not.toBeInTheDocument()
    expect(screen.getByText('Show completed (2)')).toBeInTheDocument()
  })

  it('shows completed epics when toggle is clicked', async () => {
    const user = userEvent.setup()
    const backlogWithDone: BacklogEpic[] = [
      ...mockBacklog,
      {
        epic: {
          id: 'e2', project_id: 'p1', title: 'Done Epic', description: '',
          bounded_context: '', context_description: '', status: 'done',
          position: 1, created_at: '', color: '#10b981', number: 3,
        },
        features: [{
          feature: {
            id: 'f2', epic_id: 'e2', title: 'Done Feature', description: '',
            status: 'done', position: 0, created_at: '', number: 3,
          },
          tasks: [
            { id: 't3', title: 'Done task', status: 'done', priority: 'normal', number: 6 },
          ],
          task_counts: { total: 1, done: 1 },
        }],
        task_counts: { total: 1, done: 1 },
      },
    ]
    render(<BacklogTree backlog={backlogWithDone} onItemClick={vi.fn()} />)
    await user.click(screen.getByText('Show completed (2)'))
    expect(screen.getByText('Done Epic')).toBeInTheDocument()
    expect(screen.getByText('Hide completed (2)')).toBeInTheDocument()
  })

  it('renders drag handles for each epic', () => {
    render(<BacklogTree backlog={mockBacklog} onItemClick={vi.fn()} />)
    const handles = screen.getAllByLabelText('Reorder')
    // At minimum one handle per epic, feature, and task
    expect(handles.length).toBeGreaterThanOrEqual(1)
  })

  it('still navigates on title click with drag handles present', async () => {
    const user = userEvent.setup()
    const onClick = vi.fn()
    render(<BacklogTree backlog={mockBacklog} onItemClick={onClick} />)
    await user.click(screen.getByText('Auth System'))
    expect(onClick).toHaveBeenCalledWith('epic', 'e1')
  })

  it('passes reorder callbacks without error', () => {
    const onReorderEpics = vi.fn()
    const onReorderFeatures = vi.fn()
    const onReorderTasks = vi.fn()
    render(
      <BacklogTree
        backlog={mockBacklog}
        onItemClick={vi.fn()}
        onReorderEpics={onReorderEpics}
        onReorderFeatures={onReorderFeatures}
        onReorderTasks={onReorderTasks}
      />
    )
    expect(screen.getByText('Auth System')).toBeInTheDocument()
  })

  it('sorts incomplete features before completed ones when show completed is on', async () => {
    const user = userEvent.setup()
    const backlogMixed: BacklogEpic[] = [{
      epic: {
        id: 'e1', project_id: 'p1', title: 'Mixed Epic', description: '',
        bounded_context: '', context_description: '', status: 'in_progress',
        position: 0, created_at: '', color: '#7c3aed', number: 1,
      },
      features: [
        {
          feature: {
            id: 'f1', epic_id: 'e1', title: 'Finished Feature', description: '',
            status: 'done', position: 0, created_at: '', number: 1,
          },
          tasks: [
            { id: 't1', title: 'Done task', status: 'done', priority: 'normal', number: 1 },
          ],
          task_counts: { total: 1, done: 1 },
        },
        {
          feature: {
            id: 'f2', epic_id: 'e1', title: 'Active Feature', description: '',
            status: 'in_progress', position: 1, created_at: '', number: 2,
          },
          tasks: [
            { id: 't2', title: 'Active task', status: 'backlog', priority: 'normal', number: 2 },
          ],
          task_counts: { total: 1, done: 0 },
        },
      ],
      task_counts: { total: 2, done: 1 },
    }]
    render(<BacklogTree backlog={backlogMixed} onItemClick={vi.fn()} />)
    // Toggle show completed
    await user.click(screen.getByText('Show completed (1)'))
    // Both features should be visible now
    expect(screen.getByText('Active Feature')).toBeInTheDocument()
    expect(screen.getByText('Finished Feature')).toBeInTheDocument()
    // Active Feature should come before Finished Feature in the DOM
    const activeEl = screen.getByText('Active Feature')
    const finishedEl = screen.getByText('Finished Feature')
    // compareDocumentPosition bit 4 = DOCUMENT_POSITION_FOLLOWING
    expect(activeEl.compareDocumentPosition(finishedEl) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('sorts incomplete epics before completed ones when show completed is on', async () => {
    const user = userEvent.setup()
    const backlogMixed: BacklogEpic[] = [
      {
        epic: {
          id: 'e1', project_id: 'p1', title: 'Done Epic', description: '',
          bounded_context: '', context_description: '', status: 'done',
          position: 0, created_at: '', color: '#10b981', number: 1,
        },
        features: [{
          feature: {
            id: 'f1', epic_id: 'e1', title: 'Done Feature', description: '',
            status: 'done', position: 0, created_at: '', number: 1,
          },
          tasks: [
            { id: 't1', title: 'Done task', status: 'done', priority: 'normal', number: 1 },
          ],
          task_counts: { total: 1, done: 1 },
        }],
        task_counts: { total: 1, done: 1 },
      },
      {
        epic: {
          id: 'e2', project_id: 'p1', title: 'Active Epic', description: '',
          bounded_context: '', context_description: '', status: 'in_progress',
          position: 1, created_at: '', color: '#7c3aed', number: 2,
        },
        features: [{
          feature: {
            id: 'f2', epic_id: 'e2', title: 'Active Feature', description: '',
            status: 'in_progress', position: 0, created_at: '', number: 2,
          },
          tasks: [
            { id: 't2', title: 'Active task', status: 'backlog', priority: 'normal', number: 2 },
          ],
          task_counts: { total: 1, done: 0 },
        }],
        task_counts: { total: 1, done: 0 },
      },
    ]
    render(<BacklogTree backlog={backlogMixed} onItemClick={vi.fn()} />)
    await user.click(screen.getByText('Show completed (2)'))
    // Both epics visible
    expect(screen.getByText('Active Epic')).toBeInTheDocument()
    expect(screen.getByText('Done Epic')).toBeInTheDocument()
    // Active Epic should come before Done Epic
    const activeEl = screen.getByText('Active Epic')
    const doneEl = screen.getByText('Done Epic')
    expect(activeEl.compareDocumentPosition(doneEl) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('renders collapse all button when tree is expanded', () => {
    render(<BacklogTree backlog={mockBacklog} onItemClick={vi.fn()} />)
    expect(screen.getByTitle('Collapse all')).toBeInTheDocument()
    expect(screen.getByText(/Collapse all/)).toBeInTheDocument()
  })

  it('collapses all epics and features when collapse all is clicked', async () => {
    const user = userEvent.setup()
    render(<BacklogTree backlog={mockBacklog} onItemClick={vi.fn()} />)
    // Features and tasks visible initially
    expect(screen.getByText('OAuth')).toBeInTheDocument()
    expect(screen.getByText('Callback handler')).toBeInTheDocument()
    // Click collapse all
    await user.click(screen.getByText(/Collapse all/))
    // Features and tasks hidden
    expect(screen.queryByText('OAuth')).not.toBeInTheDocument()
    expect(screen.queryByText('Callback handler')).not.toBeInTheDocument()
    // Button now shows expand all
    expect(screen.getByText(/Expand all/)).toBeInTheDocument()
  })

  it('expands all epics and features when expand all is clicked', async () => {
    const user = userEvent.setup()
    render(<BacklogTree backlog={mockBacklog} onItemClick={vi.fn()} />)
    // Collapse first
    await user.click(screen.getByText(/Collapse all/))
    expect(screen.queryByText('OAuth')).not.toBeInTheDocument()
    // Expand all
    await user.click(screen.getByText(/Expand all/))
    expect(screen.getByText('OAuth')).toBeInTheDocument()
    expect(screen.getByText('Callback handler')).toBeInTheDocument()
  })

  it('shows expand all when some items are manually collapsed', async () => {
    const user = userEvent.setup()
    render(<BacklogTree backlog={mockBacklog} onItemClick={vi.fn()} />)
    // Collapse the epic manually via the toggle
    const toggles = screen.getAllByText('\u25BC')
    await user.click(toggles[0]) // collapse epic
    // Button should now show expand all since not everything is expanded
    expect(screen.getByText(/Expand all/)).toBeInTheDocument()
  })

  it('hides completed features within a visible epic', () => {
    const backlogMixed: BacklogEpic[] = [{
      epic: {
        id: 'e1', project_id: 'p1', title: 'Mixed Epic', description: '',
        bounded_context: '', context_description: '', status: 'in_progress',
        position: 0, created_at: '', color: '#7c3aed', number: 1,
      },
      features: [
        {
          feature: {
            id: 'f1', epic_id: 'e1', title: 'Active Feature', description: '',
            status: 'in_progress', position: 0, created_at: '', number: 1,
          },
          tasks: [
            { id: 't1', title: 'Active task', status: 'backlog', priority: 'normal', number: 1 },
          ],
          task_counts: { total: 1, done: 0 },
        },
        {
          feature: {
            id: 'f2', epic_id: 'e1', title: 'Finished Feature', description: '',
            status: 'done', position: 1, created_at: '', number: 2,
          },
          tasks: [
            { id: 't2', title: 'Done task', status: 'done', priority: 'normal', number: 2 },
          ],
          task_counts: { total: 1, done: 1 },
        },
      ],
      task_counts: { total: 2, done: 1 },
    }]
    render(<BacklogTree backlog={backlogMixed} onItemClick={vi.fn()} />)
    expect(screen.getByText('Active Feature')).toBeInTheDocument()
    expect(screen.queryByText('Finished Feature')).not.toBeInTheDocument()
  })
})
