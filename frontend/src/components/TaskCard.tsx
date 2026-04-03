import type { TaskCard as TaskCardType } from '../api/types'
import './TaskCard.css'

interface TaskCardProps {
  task: TaskCardType
  onClick: () => void
}

export function TaskCard({ task, onClick }: TaskCardProps) {
  return (
    <div className="task-card" onClick={onClick} role="button" tabIndex={0}>
      <div className="task-breadcrumb">
        {task.epic_title} / {task.feature_title}
      </div>
      <div className="task-title">{task.title}</div>
      <div className="task-meta">
        {task.priority === 'expedite' && (
          <span className="task-priority">expedite</span>
        )}
        {task.worktree_id && (
          <span className="task-worktree">agent assigned</span>
        )}
      </div>
    </div>
  )
}
