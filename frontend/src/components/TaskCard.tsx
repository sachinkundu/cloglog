import type { TaskCard as TaskCardType } from '../api/types'
import { formatEntityNumber } from '../utils/format'
import { BreadcrumbPills } from './BreadcrumbPills'
import { PrLink } from './PrLink'
import './TaskCard.css'

interface TaskCardProps {
  task: TaskCardType
  onClick: () => void
  worktreeNames?: Record<string, string>
}

export function TaskCard({ task, onClick, worktreeNames }: TaskCardProps) {
  return (
    <div
      className="task-card"
      onClick={onClick}
      role="button"
      tabIndex={0}
    >
      <BreadcrumbPills
        epicTitle={task.epic_title}
        featureTitle={task.feature_title}
        epicColor={task.epic_color}
      />
      <div className="task-title">
        {task.number > 0 && <span className="entity-number">{formatEntityNumber('task', task.number)} </span>}
        {task.title}
      </div>
      <div className="task-meta">
        {task.priority === 'expedite' && (
          <span className="task-priority">expedite</span>
        )}
        {task.worktree_id && (
          <span className="task-worktree">{worktreeNames?.[task.worktree_id] ?? 'agent (removed)'}</span>
        )}
        {task.pr_url && (
          <PrLink
            url={task.pr_url}
            merged={task.pr_merged}
            codexReviewed={task.status === 'review' && task.codex_review_picked_up}
          />
        )}
      </div>
    </div>
  )
}
