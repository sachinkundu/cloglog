import type { BoardResponse } from '../api/types'

interface BoardHeaderProps {
  board: BoardResponse
}

export function BoardHeader({ board }: BoardHeaderProps) {
  const pct = board.total_tasks > 0
    ? Math.round((board.done_count / board.total_tasks) * 100)
    : 0

  return (
    <div style={{
      padding: '20px 24px 12px',
      display: 'flex',
      alignItems: 'baseline',
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
    </div>
  )
}
