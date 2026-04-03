import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { BoardResponse, SSEEvent, Worktree } from '../api/types'
import { useSSE } from './useSSE'

export function useBoard(projectId: string | null) {
  const [board, setBoard] = useState<BoardResponse | null>(null)
  const [worktrees, setWorktrees] = useState<Worktree[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchBoard = useCallback(async () => {
    if (!projectId) return
    setLoading(true)
    try {
      const [boardData, wtData] = await Promise.all([
        api.getBoard(projectId),
        api.getWorktrees(projectId),
      ])
      setBoard(boardData)
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

  // Re-fetch on SSE events
  const handleSSE = useCallback((_event: SSEEvent) => {
    fetchBoard()
  }, [fetchBoard])

  useSSE(projectId, handleSSE)

  return { board, worktrees, loading, error, refetch: fetchBoard }
}
