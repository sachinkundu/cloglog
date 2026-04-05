import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { DependencyGraphResponse, SSEEvent } from '../api/types'
import { useSSE } from './useSSE'

export function useDependencyGraph(projectId: string | null) {
  const [graph, setGraph] = useState<DependencyGraphResponse | null>(null)
  const [loading, setLoading] = useState(false)

  const fetchGraph = useCallback(async () => {
    if (!projectId) return
    setLoading(true)
    try {
      const data = await api.getDependencyGraph(projectId)
      setGraph(data)
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => { fetchGraph() }, [fetchGraph])

  useSSE(projectId, useCallback((event: SSEEvent) => {
    if (event.type === 'dependency_added' || event.type === 'dependency_removed'
        || event.type === 'feature_created' || event.type === 'feature_deleted') {
      fetchGraph()
    }
  }, [fetchGraph]))

  return { graph, loading, refetch: fetchGraph }
}
