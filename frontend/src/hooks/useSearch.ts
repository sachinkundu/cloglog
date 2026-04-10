import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { SearchResult } from '../api/types'
import { parseSearchQualifiers } from '../lib/searchQualifiers'
import type { ParsedQuery } from '../lib/searchQualifiers'

interface UseSearchReturn {
  results: SearchResult[]
  loading: boolean
  /** The currently active parsed query (qualifiers + text) */
  parsed: ParsedQuery | null
  search: (query: string) => void
  clear: () => void
}

export function useSearch(projectId: string): UseSearchReturn {
  const [results, setResults] = useState<SearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const [parsed, setParsed] = useState<ParsedQuery | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clear = useCallback(() => {
    setResults([])
    setLoading(false)
    setParsed(null)
    if (timerRef.current) clearTimeout(timerRef.current)
    if (abortRef.current) abortRef.current.abort()
  }, [])

  const search = useCallback((query: string) => {
    const pq = parseSearchQualifiers(query)
    setParsed(pq)

    // If there's no text and no qualifiers, clear
    if (!pq.text && !pq.statusFilter) {
      clear()
      return
    }

    // Need at least some text to search (qualifiers alone aren't enough
    // since the backend requires q with min_length=1)
    if (!pq.text) {
      clear()
      // Keep parsed state so UI can show active filters
      setParsed(pq)
      return
    }

    setLoading(true)
    if (timerRef.current) clearTimeout(timerRef.current)
    if (abortRef.current) abortRef.current.abort()

    timerRef.current = setTimeout(async () => {
      const controller = new AbortController()
      abortRef.current = controller
      try {
        const res = await api.search(
          projectId,
          pq.text,
          20,
          controller.signal,
          pq.statusFilter,
        )
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

  return { results, loading, parsed, search, clear }
}
