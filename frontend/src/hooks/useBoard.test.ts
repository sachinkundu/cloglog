import { renderHook, act, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

// Track SSE handler so we can simulate events
let sseHandler: ((event: { type: string; data: Record<string, string> }) => void) | null = null

vi.mock('./useSSE', () => ({
  useSSE: (_projectId: string | null, handler: (event: { type: string; data: Record<string, string> }) => void) => {
    sseHandler = handler
  },
}))

vi.mock('../api/client', () => ({
  api: {
    getBoard: vi.fn(),
    getBacklog: vi.fn(),
    getWorktrees: vi.fn(),
    streamUrl: vi.fn().mockReturnValue('http://test/stream'),
  },
}))

import { useBoard } from './useBoard'
import { api } from '../api/client'
import type { BoardResponse, Worktree } from '../api/types'

const mockApi = vi.mocked(api)

const makeBoard = (columns: BoardResponse['columns']): BoardResponse => ({
  project_id: 'p1',
  project_name: 'Test',
  columns,
  total_tasks: columns.reduce((n, c) => n + c.tasks.length, 0),
  done_count: columns.find(c => c.status === 'done')?.tasks.length ?? 0,
})

const makeTask = (id: string, title: string, status: string) => ({
  id,
  feature_id: 'f1',
  title,
  description: '',
  status,
  priority: 'normal' as const,
  task_type: 'task',
  pr_url: null as string | null,
  pr_merged: false,
  worktree_id: null,
  position: 0,
  number: 1,
  archived: false,
  created_at: '',
  updated_at: '',
  epic_title: 'Epic',
  feature_title: 'Feature',
  epic_color: '#7c3aed',
})

const worktrees: Worktree[] = []

describe('useBoard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sseHandler = null
  })

  it('fetches board data on mount', async () => {
    const board = makeBoard([{ status: 'backlog', tasks: [makeTask('t1', 'Task', 'backlog')] }])
    mockApi.getBoard.mockResolvedValue(board)
    mockApi.getBacklog.mockResolvedValue([])
    mockApi.getWorktrees.mockResolvedValue(worktrees)

    const { result } = renderHook(() => useBoard('p1'))

    await waitFor(() => {
      expect(result.current.board).toEqual(board)
    })
    expect(mockApi.getBoard).toHaveBeenCalledWith('p1')
  })

  it('moves task between columns on task_status_changed SSE event without refetching', async () => {
    const board = makeBoard([
      { status: 'in_progress', tasks: [makeTask('t1', 'Moving Task', 'in_progress')] },
      { status: 'testing', tasks: [] },
    ])
    mockApi.getBoard.mockResolvedValue(board)
    mockApi.getBacklog.mockResolvedValue([])
    mockApi.getWorktrees.mockResolvedValue(worktrees)

    const { result } = renderHook(() => useBoard('p1'))

    await waitFor(() => {
      expect(result.current.board).not.toBeNull()
    })

    // Clear mock call count after initial fetch
    mockApi.getBoard.mockClear()

    // Simulate SSE: task t1 moved from in_progress to testing
    act(() => {
      sseHandler!({ type: 'task_status_changed', data: { task_id: 't1', new_status: 'testing' } })
    })

    // Board should NOT refetch — it should update in-place
    expect(mockApi.getBoard).not.toHaveBeenCalled()

    // Task should now be in the testing column
    const testingCol = result.current.board!.columns.find(c => c.status === 'testing')
    expect(testingCol!.tasks).toHaveLength(1)
    expect(testingCol!.tasks[0].id).toBe('t1')

    // Task should be removed from in_progress column
    const inProgressCol = result.current.board!.columns.find(c => c.status === 'in_progress')
    expect(inProgressCol!.tasks).toHaveLength(0)
  })

  it('creates destination column if it does not exist yet', async () => {
    const board = makeBoard([
      { status: 'in_progress', tasks: [makeTask('t1', 'Task', 'in_progress')] },
    ])
    mockApi.getBoard.mockResolvedValue(board)
    mockApi.getBacklog.mockResolvedValue([])
    mockApi.getWorktrees.mockResolvedValue(worktrees)

    const { result } = renderHook(() => useBoard('p1'))

    await waitFor(() => {
      expect(result.current.board).not.toBeNull()
    })

    act(() => {
      sseHandler!({ type: 'task_status_changed', data: { task_id: 't1', new_status: 'review' } })
    })

    const reviewCol = result.current.board!.columns.find(c => c.status === 'review')
    expect(reviewCol).toBeDefined()
    expect(reviewCol!.tasks[0].id).toBe('t1')
  })

  it('updates worktree status in-place on worktree_online SSE event', async () => {
    const board = makeBoard([{ status: 'backlog', tasks: [] }])
    const wts: Worktree[] = [
      { id: 'wt1', project_id: 'p1', name: 'wt-ui', worktree_path: '/tmp', branch_name: 'main', status: 'offline', current_task_id: null, last_heartbeat: null, created_at: '' },
    ]
    mockApi.getBoard.mockResolvedValue(board)
    mockApi.getBacklog.mockResolvedValue([])
    mockApi.getWorktrees.mockResolvedValue(wts)

    const { result } = renderHook(() => useBoard('p1'))

    await waitFor(() => {
      expect(result.current.worktrees).toHaveLength(1)
    })

    mockApi.getBoard.mockClear()

    act(() => {
      sseHandler!({ type: 'worktree_online', data: { worktree_id: 'wt1' } })
    })

    // Should NOT refetch — update in-place
    expect(mockApi.getBoard).not.toHaveBeenCalled()
    expect(result.current.worktrees[0].status).toBe('online')
  })

  it('updates worktree status on worktree_offline SSE event', async () => {
    const board = makeBoard([{ status: 'backlog', tasks: [] }])
    const wts: Worktree[] = [
      { id: 'wt1', project_id: 'p1', name: 'wt-ui', worktree_path: '/tmp', branch_name: 'main', status: 'online', current_task_id: null, last_heartbeat: null, created_at: '' },
    ]
    mockApi.getBoard.mockResolvedValue(board)
    mockApi.getBacklog.mockResolvedValue([])
    mockApi.getWorktrees.mockResolvedValue(wts)

    const { result } = renderHook(() => useBoard('p1'))

    await waitFor(() => {
      expect(result.current.worktrees).toHaveLength(1)
    })

    mockApi.getBoard.mockClear()

    act(() => {
      sseHandler!({ type: 'worktree_offline', data: { worktree_id: 'wt1' } })
    })

    expect(mockApi.getBoard).not.toHaveBeenCalled()
    expect(result.current.worktrees[0].status).toBe('offline')
  })

  it('falls back to full refetch for unknown worktree SSE events', async () => {
    const board = makeBoard([{ status: 'backlog', tasks: [] }])
    mockApi.getBoard.mockResolvedValue(board)
    mockApi.getBacklog.mockResolvedValue([])
    mockApi.getWorktrees.mockResolvedValue(worktrees)

    const { result } = renderHook(() => useBoard('p1'))

    await waitFor(() => {
      expect(result.current.board).not.toBeNull()
    })

    mockApi.getBoard.mockClear()

    act(() => {
      sseHandler!({ type: 'worktree_online', data: { worktree_id: 'unknown-wt' } })
    })

    expect(mockApi.getBoard).toHaveBeenCalled()
  })

  it('falls back to full refetch for document_attached SSE events', async () => {
    const board = makeBoard([{ status: 'backlog', tasks: [] }])
    mockApi.getBoard.mockResolvedValue(board)
    mockApi.getBacklog.mockResolvedValue([])
    mockApi.getWorktrees.mockResolvedValue(worktrees)

    const { result } = renderHook(() => useBoard('p1'))

    await waitFor(() => {
      expect(result.current.board).not.toBeNull()
    })

    mockApi.getBoard.mockClear()

    act(() => {
      sseHandler!({ type: 'document_attached', data: { document_id: 'd1' } })
    })

    expect(mockApi.getBoard).toHaveBeenCalled()
  })

  it('moveTask optimistically moves a task to a new column', async () => {
    const board = makeBoard([
      { status: 'in_progress', tasks: [makeTask('t1', 'Task', 'in_progress')] },
      { status: 'review', tasks: [] },
    ])
    mockApi.getBoard.mockResolvedValue(board)
    mockApi.getBacklog.mockResolvedValue([])
    mockApi.getWorktrees.mockResolvedValue(worktrees)

    const { result } = renderHook(() => useBoard('p1'))

    await waitFor(() => {
      expect(result.current.board).not.toBeNull()
    })

    act(() => {
      result.current.moveTask('t1', 'review')
    })

    const reviewCol = result.current.board!.columns.find(c => c.status === 'review')
    expect(reviewCol!.tasks).toHaveLength(1)
    expect(reviewCol!.tasks[0].id).toBe('t1')

    const ipCol = result.current.board!.columns.find(c => c.status === 'in_progress')
    expect(ipCol!.tasks).toHaveLength(0)
  })

  it('moveTask is a no-op when task is already in the target column', async () => {
    const board = makeBoard([
      { status: 'review', tasks: [makeTask('t1', 'Task', 'review')] },
    ])
    mockApi.getBoard.mockResolvedValue(board)
    mockApi.getBacklog.mockResolvedValue([])
    mockApi.getWorktrees.mockResolvedValue(worktrees)

    const { result } = renderHook(() => useBoard('p1'))

    await waitFor(() => {
      expect(result.current.board).not.toBeNull()
    })

    const boardBefore = result.current.board

    act(() => {
      result.current.moveTask('t1', 'review')
    })

    // Should return same reference — no state change
    expect(result.current.board).toBe(boardBefore)
  })

  it('SSE task_status_changed is a no-op when task is already in the target column', async () => {
    const board = makeBoard([
      { status: 'in_progress', tasks: [makeTask('t1', 'Task', 'in_progress')] },
      { status: 'review', tasks: [] },
    ])
    mockApi.getBoard.mockResolvedValue(board)
    mockApi.getBacklog.mockResolvedValue([])
    mockApi.getWorktrees.mockResolvedValue(worktrees)

    const { result } = renderHook(() => useBoard('p1'))

    await waitFor(() => {
      expect(result.current.board).not.toBeNull()
    })

    // Simulate optimistic move first
    act(() => {
      result.current.moveTask('t1', 'review')
    })

    mockApi.getBoard.mockClear()
    const boardAfterMove = result.current.board

    // SSE arrives for the same move — should be a no-op
    act(() => {
      sseHandler!({ type: 'task_status_changed', data: { task_id: 't1', new_status: 'review' } })
    })

    expect(mockApi.getBoard).not.toHaveBeenCalled()
    expect(result.current.board).toBe(boardAfterMove)
  })

  it('falls back to refetch when task_id not found in current board', async () => {
    const board = makeBoard([
      { status: 'in_progress', tasks: [makeTask('t1', 'Task', 'in_progress')] },
    ])
    mockApi.getBoard.mockResolvedValue(board)
    mockApi.getBacklog.mockResolvedValue([])
    mockApi.getWorktrees.mockResolvedValue(worktrees)

    const { result } = renderHook(() => useBoard('p1'))

    await waitFor(() => {
      expect(result.current.board).not.toBeNull()
    })

    mockApi.getBoard.mockClear()

    act(() => {
      sseHandler!({ type: 'task_status_changed', data: { task_id: 'unknown', new_status: 'done' } })
    })

    // Unknown task — should fall back to refetch
    expect(mockApi.getBoard).toHaveBeenCalled()
  })
})
