import { useState } from 'react'
import type { BacklogEpic } from '../api/types'
import './BacklogTree.css'

interface BacklogTreeProps {
  backlog: BacklogEpic[]
  onItemClick: (type: 'epic' | 'feature' | 'task', id: string) => void
}

export function BacklogTree({ backlog, onItemClick }: BacklogTreeProps) {
  const [expandedEpics, setExpandedEpics] = useState<Set<string>>(
    new Set(backlog.map(e => e.epic.id))
  )
  const [expandedFeatures, setExpandedFeatures] = useState<Set<string>>(
    new Set(backlog.flatMap(e => e.features.map(f => f.feature.id)))
  )

  const toggleEpic = (id: string) => {
    setExpandedEpics(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleFeature = (id: string) => {
    setExpandedFeatures(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <div className="backlog-tree">
      {backlog.map(({ epic, features, task_counts }) => (
        <div key={epic.id} className="backlog-epic">
          <div
            className="backlog-epic-header"
            style={{ borderLeftColor: epic.color }}
          >
            <span
              className="backlog-toggle"
              onClick={() => toggleEpic(epic.id)}
            >
              {expandedEpics.has(epic.id) ? '\u25BC' : '\u25B6'}
            </span>
            <span
              className="backlog-epic-title"
              style={{ color: epic.color }}
              onClick={() => onItemClick('epic', epic.id)}
            >
              {epic.title}
            </span>
            <span className="backlog-count">
              {task_counts.done}/{task_counts.total}
            </span>
          </div>

          {expandedEpics.has(epic.id) && features.map(({ feature, tasks, task_counts: fc }) => (
            <div key={feature.id} className="backlog-feature">
              <div className="backlog-feature-header">
                <span
                  className="backlog-toggle"
                  onClick={() => toggleFeature(feature.id)}
                >
                  {expandedFeatures.has(feature.id) ? '\u25BC' : '\u25B6'}
                </span>
                <span
                  className="backlog-feature-title"
                  onClick={() => onItemClick('feature', feature.id)}
                >
                  {feature.title}
                </span>
                <span className="backlog-count">{fc.done}/{fc.total}</span>
              </div>

              {expandedFeatures.has(feature.id) && (
                <div className="backlog-tasks">
                  {tasks.map(task => (
                    <div
                      key={task.id}
                      className="backlog-task"
                      onClick={() => onItemClick('task', task.id)}
                    >
                      {task.title}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}
