import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { SearchResult } from '../api/types'

interface UseSearchReturn {
  results: SearchResult[]
  loading: boolean
  search: (query: string) => void
  clear: () => void
}

export function useSearch(projectId: string): UseSearchReturn {
  const [results, setResults] = useState<SearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clear = useCallback(() => {
    setResults([])
    setLoading(false)
    if (timerRef.current) clearTimeout(timerRef.current)
    if (abortRef.current) abortRef.current.abort()
  }, [])

  const search = useCallback((query: string) => {
    if (!query.trim()) {
      clear()
      return
    }

    setLoading(true)
    if (timerRef.current) clearTimeout(timerRef.current)
    if (abortRef.current) abortRef.current.abort()

    timerRef.current = setTimeout(async () => {
      const controller = new AbortController()
      abortRef.current = controller
      try {
        const res = await api.search(projectId, query, 20, controller.signal)
        if (!controller.signal.aborted) {
          setResults(res.results)
          setLoading(false)
        }
      } catch {
        if (!controller.signal.aborted) {
          setResults([])
          setLoading(false)
        }
      }
    }, 200)
  }, [projectId, clear])

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
      if (abortRef.current) abortRef.current.abort()
    }
  }, [])

  return { results, loading, search, clear }
}
