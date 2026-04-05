import { useState, useCallback } from 'react'
import {
  DndContext,
  closestCenter,
  PointerSensor,
  TouchSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import {
  SortableContext,
  verticalListSortingStrategy,
  arrayMove,
} from '@dnd-kit/sortable'
import { restrictToVerticalAxis } from '@dnd-kit/modifiers'
import type { BacklogEpic } from '../api/types'
import { formatEntityNumber } from '../utils/format'
import { SortableItem } from './SortableItem'
import './BacklogTree.css'

interface BacklogTreeProps {
  backlog: BacklogEpic[]
  onItemClick: (type: 'epic' | 'feature' | 'task', id: string) => void
  onReorderEpics?: (items: { id: string; position: number }[]) => void
  onReorderFeatures?: (epicId: string, items: { id: string; position: number }[]) => void
  onReorderTasks?: (featureId: string, items: { id: string; position: number }[]) => void
}

const ACTIVE_STATUSES = new Set(['in_progress', 'review'])

function SegmentedProgress({ tasks }: { tasks: Array<{ status: string }> }) {
  const total = tasks.length
  if (total === 0) return null

  const done = tasks.filter(t => t.status === 'done').length
  const active = tasks.filter(t => ACTIVE_STATUSES.has(t.status)).length
  return (
    <div className="seg-progress" title={`${done} done · ${active} active · ${total - done - active} remaining`}>
      <div className="seg-bar">
        {done > 0 && <div className="seg-done" style={{ width: `${(done / total) * 100}%` }} />}
        {active > 0 && <div className="seg-active" style={{ width: `${(active / total) * 100}%` }} />}
      </div>
    </div>
  )
}

function isFullyDone(counts: { total: number; done: number }) {
  return counts.total > 0 && counts.done === counts.total
}

export function BacklogTree({ backlog, onItemClick, onReorderEpics, onReorderFeatures, onReorderTasks }: BacklogTreeProps) {
  const [showCompleted, setShowCompleted] = useState(
    () => localStorage.getItem('backlog-show-completed') === 'true'
  )
  const [expandedEpics, setExpandedEpics] = useState<Set<string>>(
    new Set(backlog.map(e => e.epic.id))
  )
  const [expandedFeatures, setExpandedFeatures] = useState<Set<string>>(
    new Set(backlog.flatMap(e => e.features.map(f => f.feature.id)))
  )
  const [localBacklog, setLocalBacklog] = useState(backlog)

  // Sync from props only when items are added/removed/status-changed — not on reorder.
  // This preserves drag ordering while picking up structural changes.
  const getContentKey = (bl: BacklogEpic[]) =>
    bl.flatMap(e => [e.epic.id, ...e.features.flatMap(f => [f.feature.id, f.feature.status, ...f.tasks.map(t => t.id + t.status)])]).sort().join(',')
  const propKey = getContentKey(backlog)
  const localKey = getContentKey(localBacklog)
  if (propKey !== localKey) {
    setLocalBacklog(backlog)
  }

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 200, tolerance: 5 } }),
  )

  const toggleShowCompleted = () => {
    setShowCompleted(prev => {
      const next = !prev
      localStorage.setItem('backlog-show-completed', String(next))
      return next
    })
  }

  const visibleBacklog = showCompleted
    ? localBacklog
    : localBacklog.filter(e => !isFullyDone(e.task_counts))

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

  const handleEpicDragEnd = useCallback((event: DragEndEvent) => {
    const { active, over } = event
    if (!over || active.id === over.id) return

    const oldIndex = visibleBacklog.findIndex(e => e.epic.id === active.id)
    const newIndex = visibleBacklog.findIndex(e => e.epic.id === over.id)
    if (oldIndex === -1 || newIndex === -1) return

    const newOrder = arrayMove(localBacklog, oldIndex, newIndex)
    setLocalBacklog(newOrder)

    const items = newOrder.map((e, i) => ({ id: e.epic.id, position: i * 1000 }))
    onReorderEpics?.(items)
  }, [visibleBacklog, localBacklog, onReorderEpics])

  const handleFeatureDragEnd = useCallback((epicId: string, event: DragEndEvent) => {
    const { active, over } = event
    if (!over || active.id === over.id) return

    setLocalBacklog(prev => {
      const next = prev.map(epicEntry => {
        if (epicEntry.epic.id !== epicId) return epicEntry
        const features = [...epicEntry.features]
        const oldIdx = features.findIndex(f => f.feature.id === active.id)
        const newIdx = features.findIndex(f => f.feature.id === over.id)
        if (oldIdx === -1 || newIdx === -1) return epicEntry
        const reordered = arrayMove(features, oldIdx, newIdx)
        const items = reordered.map((f, i) => ({ id: f.feature.id, position: i * 1000 }))
        onReorderFeatures?.(epicId, items)
        return { ...epicEntry, features: reordered }
      })
      return next
    })
  }, [onReorderFeatures])

  const handleTaskDragEnd = useCallback((featureId: string, event: DragEndEvent) => {
    const { active, over } = event
    if (!over || active.id === over.id) return

    setLocalBacklog(prev => {
      const next = prev.map(epicEntry => ({
        ...epicEntry,
        features: epicEntry.features.map(featEntry => {
          if (featEntry.feature.id !== featureId) return featEntry
          const tasks = [...featEntry.tasks]
          const oldIdx = tasks.findIndex(t => t.id === active.id)
          const newIdx = tasks.findIndex(t => t.id === over.id)
          if (oldIdx === -1 || newIdx === -1) return featEntry
          const reordered = arrayMove(tasks, oldIdx, newIdx)
          const items = reordered.map((t, i) => ({ id: t.id, position: i * 1000 }))
          onReorderTasks?.(featureId, items)
          return { ...featEntry, tasks: reordered }
        }),
      }))
      return next
    })
  }, [onReorderTasks])

  const completedEpics = localBacklog.filter(e => isFullyDone(e.task_counts)).length
  const completedFeatures = localBacklog.reduce(
    (sum, e) => sum + e.features.filter(f => isFullyDone(f.task_counts)).length, 0
  )
  const completedCount = completedEpics + completedFeatures

  return (
    <div className="backlog-tree">
      {completedCount > 0 && (
        <button className="backlog-completed-toggle" onClick={toggleShowCompleted}>
          {showCompleted ? 'Hide' : 'Show'} completed ({completedCount})
        </button>
      )}
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        modifiers={[restrictToVerticalAxis]}
        onDragEnd={handleEpicDragEnd}
      >
        <SortableContext
          items={visibleBacklog.map(e => e.epic.id)}
          strategy={verticalListSortingStrategy}
        >
          {visibleBacklog.map(({ epic, features, task_counts }) => {
            const visibleFeatures = showCompleted
              ? features
              : features.filter(f => !isFullyDone(f.task_counts))
            const allTasks = visibleFeatures.flatMap(f => f.tasks)

            return (
              <SortableItem key={epic.id} id={epic.id}>
                <div className="backlog-epic">
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
                      {epic.number != null && epic.number > 0 && <span className="entity-number">{formatEntityNumber('epic', epic.number)} </span>}
                      {epic.title}
                    </span>
                    <SegmentedProgress tasks={allTasks} />
                  </div>

                  {expandedEpics.has(epic.id) && (
                    <DndContext
                      sensors={sensors}
                      collisionDetection={closestCenter}
                      modifiers={[restrictToVerticalAxis]}
                      onDragEnd={(event) => handleFeatureDragEnd(epic.id, event)}
                    >
                      <SortableContext
                        items={visibleFeatures.map(f => f.feature.id)}
                        strategy={verticalListSortingStrategy}
                      >
                        {visibleFeatures.map(({ feature, tasks }) => {
                          const backlogTasks = tasks.filter(t => t.status === 'backlog')

                          return (
                            <SortableItem key={feature.id} id={feature.id}>
                              <div className="backlog-feature">
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
                                    {feature.number != null && feature.number > 0 && <span className="entity-number">{formatEntityNumber('feature', feature.number)} </span>}
                                    {feature.title}
                                  </span>
                                  <SegmentedProgress tasks={tasks} />
                                </div>

                                {expandedFeatures.has(feature.id) && backlogTasks.length > 0 && (
                                  <DndContext
                                    sensors={sensors}
                                    collisionDetection={closestCenter}
                                    modifiers={[restrictToVerticalAxis]}
                                    onDragEnd={(event) => handleTaskDragEnd(feature.id, event)}
                                  >
                                    <SortableContext
                                      items={backlogTasks.map(t => t.id)}
                                      strategy={verticalListSortingStrategy}
                                    >
                                      <div className="backlog-tasks">
                                        {backlogTasks.map(task => (
                                          <SortableItem key={task.id} id={task.id}>
                                            <div
                                              className="backlog-task"
                                              onClick={() => onItemClick('task', task.id)}
                                            >
                                              {task.number != null && task.number > 0 && <span className="entity-number">{formatEntityNumber('task', task.number)} </span>}
                                              {task.title}
                                            </div>
                                          </SortableItem>
                                        ))}
                                      </div>
                                    </SortableContext>
                                  </DndContext>
                                )}
                              </div>
                            </SortableItem>
                          )
                        })}
                      </SortableContext>
                    </DndContext>
                  )}
                </div>
              </SortableItem>
            )
          })}
        </SortableContext>
      </DndContext>
    </div>
  )
}
