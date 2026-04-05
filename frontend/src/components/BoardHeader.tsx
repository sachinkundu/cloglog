import type { BoardResponse } from '../api/types'
import { SearchWidget } from './SearchWidget'

interface BoardHeaderProps {
  board: BoardResponse
  projectId: string
  onItemClick: (type: 'epic' | 'feature' | 'task', id: string) => void
}

export function BoardHeader({ board, projectId, onItemClick }: BoardHeaderProps) {
  const pct = board.total_tasks > 0
    ? Math.round((board.done_count / board.total_tasks) * 100)
    : 0

  return (
    <div style={{
      padding: '20px 24px 12px',
      display: 'flex',
      alignItems: 'center',
      gap: '16px',
    }}>
      <h2 style={{
        fontFamily: 'var(--font-display)',
        fontSize: '24px',
        fontWeight: 700,
        color: 'var(--text-primary)',
      }}>
        {board.project_name}
      </h2>
      <span style={{
        fontFamily: 'var(--font-mono)',
        fontSize: '13px',
        color: 'var(--text-muted)',
      }}>
        {board.total_tasks} tasks &middot; {board.done_count} done &middot; {pct}%
      </span>
      <div style={{ marginLeft: 'auto' }}>
        <SearchWidget projectId={projectId} onSelect={onItemClick} />
      </div>
    </div>
  )
}
