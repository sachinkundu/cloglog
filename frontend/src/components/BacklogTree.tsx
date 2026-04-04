import { useState } from 'react'
import type { BacklogEpic } from '../api/types'
import './BacklogTree.css'

interface BacklogTreeProps {
  backlog: BacklogEpic[]
  onItemClick: (type: 'epic' | 'feature' | 'task', id: string) => void
}

const ACTIVE_STATUSES = new Set(['assigned', 'in_progress', 'review'])

function SegmentedProgress({ tasks }: { tasks: Array<{ status: string }> }) {
  const total = tasks.length
  if (total === 0) return null

  const done = tasks.filter(t => t.status === 'done').length
  const active = tasks.filter(t => ACTIVE_STATUSES.has(t.status)).length
  const blocked = tasks.filter(t => t.status === 'blocked').length

  return (
    <div className="seg-progress" title={`${done} done · ${active} active · ${blocked ? blocked + ' blocked · ' : ''}${total - done - active - blocked} remaining`}>
      <div className="seg-bar">
        {done > 0 && <div className="seg-done" style={{ width: `${(done / total) * 100}%` }} />}
        {active > 0 && <div className="seg-active" style={{ width: `${(active / total) * 100}%` }} />}
        {blocked > 0 && <div className="seg-blocked" style={{ width: `${(blocked / total) * 100}%` }} />}
      </div>
    </div>
  )
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
      {backlog.map(({ epic, features }) => {
        const allTasks = features.flatMap(f => f.tasks)

        return (
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
              <SegmentedProgress tasks={allTasks} />
            </div>

            {expandedEpics.has(epic.id) && features.map(({ feature, tasks }) => {
              const backlogTasks = tasks.filter(t => t.status === 'backlog')

              return (
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
                    <SegmentedProgress tasks={tasks} />
                  </div>

                  {expandedFeatures.has(feature.id) && backlogTasks.length > 0 && (
                    <div className="backlog-tasks">
                      {backlogTasks.map(task => (
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
              )
            })}
          </div>
        )
      })}
    </div>
  )
}
