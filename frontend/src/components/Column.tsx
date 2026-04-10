import { useState } from 'react'
import { useDroppable } from '@dnd-kit/core'
import type { BoardColumn as BoardColumnType } from '../api/types'
import { api } from '../api/client'
import { DraggableTaskCard } from './DraggableTaskCard'
import { TaskCard } from './TaskCard'
import './Column.css'

interface ColumnProps {
  column: BoardColumnType
  projectId?: string | null
  onTaskClick: (taskId: string) => void
  onRefresh?: () => void
  draggable?: boolean
  worktreeNames?: Record<string, string>
  agentFilter?: string | null
}

const COLUMN_LABELS: Record<string, string> = {
  backlog: 'Backlog',
  in_progress: 'In Progress',
  review: 'Review',
  done: 'Done',
}

export function Column({ column, projectId, onTaskClick, onRefresh, draggable = false, worktreeNames, agentFilter }: ColumnProps) {
  const [showArchived, setShowArchived] = useState(false)
  const isDone = column.status === 'done'

  const { setNodeRef, isOver } = useDroppable({
    id: `column-${column.status}`,
    data: { status: column.status },
  })

  const filteredTasks = agentFilter
    ? column.tasks.filter(t => t.worktree_id === agentFilter)
    : column.tasks
  const visibleTasks = isDone
    ? filteredTasks.filter(t => !t.archived)
    : filteredTasks
  const archivedTasks = isDone
    ? filteredTasks.filter(t => t.archived)
    : []

  const archiveAll = async () => {
    const unarchived = column.tasks.filter(t => !t.archived)
    await Promise.all(unarchived.map(t => api.archiveTask(t.id)))
    onRefresh?.()
  }

  const retireTask = async (taskId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    await api.retireTask(taskId)
    onRefresh?.()
  }

  const retireAll = async () => {
    if (!projectId) return
    await api.retireDone(projectId)
    onRefresh?.()
  }

  return (
    <div className={`column${isOver ? ' column-drop-target' : ''}`}>
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
      <div className="column-tasks" ref={setNodeRef}>
        {visibleTasks.map(task =>
          draggable ? (
            <DraggableTaskCard key={task.id} task={task} onClick={() => onTaskClick(task.id)} worktreeNames={worktreeNames} />
          ) : (
            <TaskCard key={task.id} task={task} onClick={() => onTaskClick(task.id)} worktreeNames={worktreeNames} />
          )
        )}

        {isDone && archivedTasks.length > 0 && (
          <div className="archived-section">
            <div className="archived-header">
              <button
                className="archived-toggle"
                onClick={() => setShowArchived(prev => !prev)}
              >
                <span className="backlog-toggle">{showArchived ? '\u25BC' : '\u25B6'}</span>
                Archived ({archivedTasks.length})
              </button>
              {showArchived && (
                <button className="retire-all-btn" onClick={retireAll} title="Retire all archived tasks">
                  Retire All
                </button>
              )}
            </div>
            {showArchived && (
              <div className="archived-tasks">
                {archivedTasks.map(task => (
                  <div
                    key={task.id}
                    className="archived-task"
                    onClick={() => onTaskClick(task.id)}
                  >
                    <span className="archived-task-title">{task.title}</span>
                    <button
                      className="retire-btn"
                      onClick={(e) => retireTask(task.id, e)}
                      title="Retire this task"
                    >
                      Retire
                    </button>
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
