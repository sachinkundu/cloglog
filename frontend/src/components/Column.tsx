import type { BoardColumn as BoardColumnType } from '../api/types'
import { TaskCard } from './TaskCard'
import './Column.css'

interface ColumnProps {
  column: BoardColumnType
  onTaskClick: (taskId: string) => void
}

const COLUMN_LABELS: Record<string, string> = {
  backlog: 'Backlog',
  assigned: 'Assigned',
  in_progress: 'In Progress',
  review: 'Review',
  done: 'Done',
  blocked: 'Blocked',
}

export function Column({ column, onTaskClick }: ColumnProps) {
  return (
    <div className="column">
      <div className="column-header">
        <span className={`column-dot col-${column.status}`} />
        <span className="column-title">{COLUMN_LABELS[column.status] ?? column.status}</span>
        <span className="column-count">{column.tasks.length}</span>
      </div>
      <div className="column-tasks">
        {column.tasks.map(task => (
          <TaskCard key={task.id} task={task} onClick={() => onTaskClick(task.id)} />
        ))}
      </div>
    </div>
  )
}
