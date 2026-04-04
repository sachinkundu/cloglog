import { useState } from 'react'
import type { BoardColumn as BoardColumnType } from '../api/types'
import { api } from '../api/client'
import { TaskCard } from './TaskCard'
import './Column.css'

interface ColumnProps {
  column: BoardColumnType
  onTaskClick: (taskId: string) => void
  onRefresh?: () => void
}

const COLUMN_LABELS: Record<string, string> = {
  backlog: 'Backlog',
  assigned: 'Assigned',
  in_progress: 'In Progress',
  testing: 'Testing',
  review: 'Review',
  done: 'Done',
  blocked: 'Blocked',
}

export function Column({ column, onTaskClick, onRefresh }: ColumnProps) {
  const [showArchived, setShowArchived] = useState(false)
  const isDone = column.status === 'done'

  const visibleTasks = isDone
    ? column.tasks.filter(t => !t.archived)
    : column.tasks
  const archivedTasks = isDone
    ? column.tasks.filter(t => t.archived)
    : []

  const archiveAll = async () => {
    const unarchived = column.tasks.filter(t => !t.archived)
    await Promise.all(unarchived.map(t => api.archiveTask(t.id)))
    onRefresh?.()
  }

  return (
    <div className="column">
      <div className="column-header">
        <span className={`column-dot col-${column.status}`} />
        <span className="column-title">{COLUMN_LABELS[column.status] ?? column.status}</span>
        <span className="column-count">{visibleTasks.length}</span>
        {isDone && visibleTasks.length > 0 && (
          <button className="archive-btn" onClick={archiveAll} title="Archive all done tasks">
            Archive
          </button>
        )}
      </div>
      <div className="column-tasks">
        {visibleTasks.map(task => (
          <TaskCard key={task.id} task={task} onClick={() => onTaskClick(task.id)} />
        ))}

        {isDone && archivedTasks.length > 0 && (
          <div className="archived-section">
            <button
              className="archived-toggle"
              onClick={() => setShowArchived(prev => !prev)}
            >
              <span className="backlog-toggle">{showArchived ? '\u25BC' : '\u25B6'}</span>
              Archived ({archivedTasks.length})
            </button>
            {showArchived && (
              <div className="archived-tasks">
                {archivedTasks.map(task => (
                  <div
                    key={task.id}
                    className="archived-task"
                    onClick={() => onTaskClick(task.id)}
                  >
                    {task.title}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
