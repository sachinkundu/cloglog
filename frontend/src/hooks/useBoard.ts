import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { BacklogEpic, BoardResponse, SSEEvent, Worktree } from '../api/types'
import { useSSE } from './useSSE'

export function useBoard(projectId: string | null) {
  const [board, setBoard] = useState<BoardResponse | null>(null)
  const [backlog, setBacklog] = useState<BacklogEpic[]>([])
  const [worktrees, setWorktrees] = useState<Worktree[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchBoard = useCallback(async () => {
    if (!projectId) return
    setLoading(true)
    try {
      const [boardData, backlogData, wtData] = await Promise.all([
        api.getBoard(projectId),
        api.getBacklog(projectId),
        api.getWorktrees(projectId),
      ])
      setBoard(boardData)
      setBacklog(backlogData)
      setWorktrees(wtData)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load board')
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    fetchBoard()
  }, [fetchBoard])

  const handleSSE = useCallback((event: SSEEvent) => {
    if (event.type === 'task_status_changed' && event.data.task_id && event.data.new_status) {
      setBoard(prev => {
        if (!prev) return prev
        const { task_id, new_status } = event.data

        let movedTask = null
        for (const col of prev.columns) {
          const task = col.tasks.find(t => t.id === task_id)
          if (task) {
            // Skip if the task is already in the target column (optimistic update already applied)
            if (col.status === new_status) return prev
            movedTask = { ...task, status: new_status }
            break
          }
        }

        if (!movedTask) {
          fetchBoard()
          return prev
        }

        const updatedColumns = prev.columns.map(col => ({
          ...col,
          tasks: col.tasks.filter(t => t.id !== task_id),
        }))

        const destCol = updatedColumns.find(c => c.status === new_status)
        if (destCol) {
          destCol.tasks = [...destCol.tasks, movedTask]
        } else {
          updatedColumns.push({ status: new_status, tasks: [movedTask] })
        }

        const doneCount = updatedColumns.find(c => c.status === 'done')?.tasks.length ?? 0
        return { ...prev, columns: updatedColumns, done_count: doneCount }
      })
    } else if (event.type === 'worktree_online' || event.type === 'worktree_offline') {
      const newStatus = event.type === 'worktree_online' ? 'online' : 'offline'
      setWorktrees(prev => {
        const wtId = event.data.worktree_id
        const found = prev.some(wt => wt.id === wtId)
        if (!found) {
          fetchBoard()
          return prev
        }
        return prev.map(wt =>
          wt.id === wtId ? { ...wt, status: newStatus } : wt
        )
      })
    } else if (event.type === 'task_retired' || event.type === 'bulk_retired') {
      fetchBoard()
    } else if (
      event.type === 'epic_reordered' ||
      event.type === 'feature_reordered' ||
      event.type === 'task_reordered'
    ) {
      // Skip refetch — the drag initiator already has the correct optimistic state.
      // Other clients viewing the same board will get the updated order on next refresh.
    } else {
      fetchBoard()
    }
  }, [fetchBoard])

  useSSE(projectId, handleSSE)

  /** Optimistically move a task to a new column without full refetch. */
  const moveTask = useCallback((taskId: string, newStatus: string) => {
    setBoard(prev => {
      if (!prev) return prev

      let movedTask = null
      for (const col of prev.columns) {
        const task = col.tasks.find(t => t.id === taskId)
        if (task) {
          if (task.status === newStatus) return prev // already there
          movedTask = { ...task, status: newStatus }
          break
        }
      }
      if (!movedTask) return prev

      const updatedColumns = prev.columns.map(col => ({
        ...col,
        tasks: col.tasks.filter(t => t.id !== taskId),
      }))
      const destCol = updatedColumns.find(c => c.status === newStatus)
      if (destCol) {
        destCol.tasks = [...destCol.tasks, movedTask]
      }
      const doneCount = updatedColumns.find(c => c.status === 'done')?.tasks.length ?? 0
      return { ...prev, columns: updatedColumns, done_count: doneCount }
    })
  }, [])

  return { board, backlog, worktrees, loading, error, refetch: fetchBoard, moveTask }
}
