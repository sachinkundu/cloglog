import { useNavigate, useLocation } from 'react-router-dom'
import type { BoardResponse } from '../api/types'

interface BoardHeaderProps {
  board: BoardResponse
  projectId: string
}

export function BoardHeader({ board, projectId }: BoardHeaderProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const isDeps = location.pathname.endsWith('/dependencies')

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
      <div style={{
        display: 'flex',
        gap: '4px',
        marginLeft: 'auto',
        background: 'var(--bg-secondary)',
        borderRadius: '6px',
        padding: '2px',
      }}>
        <button
          onClick={() => navigate(`/projects/${projectId}`)}
          style={{
            padding: '4px 12px',
            borderRadius: '4px',
            border: 'none',
            cursor: 'pointer',
            fontFamily: 'var(--font-mono)',
            fontSize: '12px',
            background: !isDeps ? 'var(--bg-tertiary)' : 'transparent',
            color: !isDeps ? 'var(--text-primary)' : 'var(--text-muted)',
          }}
        >Board</button>
        <button
          onClick={() => navigate(`/projects/${projectId}/dependencies`)}
          style={{
            padding: '4px 12px',
            borderRadius: '4px',
            border: 'none',
            cursor: 'pointer',
            fontFamily: 'var(--font-mono)',
            fontSize: '12px',
            background: isDeps ? 'var(--bg-tertiary)' : 'transparent',
            color: isDeps ? 'var(--text-primary)' : 'var(--text-muted)',
          }}
        >Dependencies</button>
      </div>
    </div>
  )
}
