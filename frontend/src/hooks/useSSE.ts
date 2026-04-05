import { useEffect, useRef } from 'react'
import { api } from '../api/client'
import type { SSEEvent } from '../api/types'

export function useSSE(
  projectId: string | null,
  onEvent: (event: SSEEvent) => void,
) {
  const onEventRef = useRef(onEvent)
  onEventRef.current = onEvent

  useEffect(() => {
    if (!projectId) return

    const url = api.streamUrl(projectId)
    const source = new EventSource(url)

    const eventTypes = [
      'task_status_changed',
      'worktree_online',
      'worktree_offline',
      'document_attached',
      'epic_created',
      'epic_deleted',
      'feature_created',
      'feature_deleted',
      'task_created',
      'task_deleted',
      'task_note_added',
      'bulk_import',
    ] as const

    for (const type of eventTypes) {
      source.addEventListener(type, (event: MessageEvent) => {
        try {
          const data = JSON.parse(event.data)
          onEventRef.current({ type, data })
        } catch {
          // Ignore malformed events
        }
      })
    }

    source.onerror = () => {
      // EventSource auto-reconnects; no action needed
    }

    return () => {
      source.close()
    }
  }, [projectId])
}
