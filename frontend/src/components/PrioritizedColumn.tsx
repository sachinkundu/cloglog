import { useCallback, useState, useMemo } from 'react'
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
import { useDroppable } from '@dnd-kit/core'
import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import type { BacklogEpic, TaskCard as TaskCardType } from '../api/types'
import { api } from '../api/client'
import { formatEntityNumber } from '../utils/format'
import { SortableItem } from './SortableItem'
import './PrioritizedColumn.css'

interface FeatureGroup {
  featureId: string
  featureTitle: string
  featureNumber: number
  featurePosition: number
  epicColor: string
  tasks: TaskCardType[]
}

interface PrioritizedColumnProps {
  tasks: TaskCardType[]
  backlog: BacklogEpic[]
  onTaskClick: (taskId: string) => void
  onItemClick: (type: 'epic' | 'feature' | 'task', id: string) => void
  onRefresh?: () => void
  onMoveTask?: (taskId: string, newStatus: string) => void
  onPrioritizeFeature?: (featureId: string, taskIds: string[]) => void
}

export function PrioritizedColumn({
  tasks, backlog, onTaskClick, onItemClick, onRefresh, onMoveTask, onPrioritizeFeature,
}: PrioritizedColumnProps) {
  const [dragOver, setDragOver] = useState(false)

  // dnd-kit droppable for task cards dragged from other board columns
  const { setNodeRef, isOver } = useDroppable({
    id: 'column-prioritized',
    data: { status: 'prioritized' },
  })

  const featureGroups = useMemo(() => {
    // Build feature metadata lookup from backlog
    const featureMeta = new Map<string, { number: number; position: number; title: string; epicColor: string }>()
    for (const epicEntry of backlog) {
      for (const feat of epicEntry.features) {
        featureMeta.set(feat.feature.id, {
          number: feat.feature.number ?? 0,
          position: feat.feature.position ?? 0,
          title: feat.feature.title,
          epicColor: epicEntry.epic.color,
        })
      }
    }

    const groups = new Map<string, FeatureGroup>()
    // Group prioritized tasks by feature
    for (const task of tasks) {
      const fid = task.feature_id ?? 'unknown'
      if (!groups.has(fid)) {
        const meta = featureMeta.get(fid)
        groups.set(fid, {
          featureId: fid,
          featureTitle: meta?.title ?? task.feature_title ?? 'Unknown Feature',
          featureNumber: meta?.number ?? 0,
          featurePosition: meta?.position ?? 0,
          epicColor: meta?.epicColor ?? task.epic_color ?? '#64748b',
          tasks: [],
        })
      }
      groups.get(fid)!.tasks.push(task)
    }
    // Add prioritized features with no prioritized tasks, and pull in
    // backlog tasks for features that have any prioritized tasks
    for (const epicEntry of backlog) {
      for (const feat of epicEntry.features) {
        const hasPrioritizedTasks = groups.has(feat.feature.id)
        const isPrioritizedFeature = feat.feature.status === 'prioritized'

        if (isPrioritizedFeature && !hasPrioritizedTasks) {
          // Taskless prioritized feature — show it with any backlog tasks
          const meta = featureMeta.get(feat.feature.id)
          groups.set(feat.feature.id, {
            featureId: feat.feature.id,
            featureTitle: meta?.title ?? feat.feature.title,
            featureNumber: meta?.number ?? feat.feature.number ?? 0,
            featurePosition: meta?.position ?? feat.feature.position ?? 0,
            epicColor: epicEntry.epic.color,
            tasks: [],
          })
        }

        // Pull in backlog tasks for features already in the prioritized column
        if (hasPrioritizedTasks || isPrioritizedFeature) {
          const group = groups.get(feat.feature.id)
          if (group) {
            const existingIds = new Set(group.tasks.map(t => t.id))
            for (const bt of feat.tasks) {
              if (bt.status === 'backlog' && !existingIds.has(bt.id)) {
                // Convert BacklogTask to a minimal TaskCard-like object
                group.tasks.push({
                  id: bt.id,
                  feature_id: feat.feature.id,
                  title: bt.title,
                  description: '',
                  status: bt.status,
                  priority: bt.priority,
                  worktree_id: null,
                  position: group.tasks.length,
                  number: bt.number,
                  archived: false,
                  retired: false,
                  created_at: '',
                  updated_at: '',
                  epic_title: epicEntry.epic.title,
                  feature_title: feat.feature.title,
                  epic_color: epicEntry.epic.color,
                  pr_merged: false,
                } as TaskCardType)
              }
            }
          }
        }
      }
    }
    return Array.from(groups.values()).sort((a, b) => a.featurePosition - b.featurePosition)
  }, [tasks, backlog])

  const [groupOrder, setGroupOrder] = useState<string[]>([])

  const orderedGroups = useMemo(() => {
    const currentIds = new Set(featureGroups.map(g => g.featureId))
    const validOrder = groupOrder.filter(id => currentIds.has(id))
    const newIds = featureGroups
      .map(g => g.featureId)
      .filter(id => !validOrder.includes(id))
    const finalOrder = [...validOrder, ...newIds]
    return finalOrder
      .map(id => featureGroups.find(g => g.featureId === id))
      .filter((g): g is FeatureGroup => g != null)
  }, [featureGroups, groupOrder])

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 200, tolerance: 5 } }),
  )

  const handleFeatureReorder = useCallback((event: DragEndEvent) => {
    const { active, over } = event
    if (!over || active.id === over.id) return

    const ids = orderedGroups.map(g => g.featureId)
    const oldIndex = ids.indexOf(active.id as string)
    const newIndex = ids.indexOf(over.id as string)
    if (oldIndex === -1 || newIndex === -1) return

    const newIds = arrayMove(ids, oldIndex, newIndex)
    setGroupOrder(newIds)

    // Persist feature positions to backend
    for (let i = 0; i < newIds.length; i++) {
      api.updateFeature(newIds[i], { position: i })
        .catch(() => onRefresh?.())
    }
  }, [orderedGroups, onRefresh])

  const handleTaskReorder = useCallback((featureId: string, event: DragEndEvent) => {
    const { active, over } = event
    if (!over || active.id === over.id) return

    const group = featureGroups.find(g => g.featureId === featureId)
    if (!group) return

    const ids = group.tasks.map(t => t.id)
    const oldIndex = ids.indexOf(active.id as string)
    const newIndex = ids.indexOf(over.id as string)
    if (oldIndex === -1 || newIndex === -1) return

    const newIds = arrayMove(ids, oldIndex, newIndex)
    const items = newIds.map((id, i) => ({ id, position: i }))
    api.reorderTasks(featureId, items).catch(() => onRefresh?.())
  }, [featureGroups, onRefresh])

  const deprioritizeFeature = useCallback((group: FeatureGroup) => {
    const updates: Promise<unknown>[] = group.tasks.map(t =>
      api.updateTask(t.id, { status: 'backlog' })
    )
    updates.push(api.updateFeature(group.featureId, { status: 'planned' }))
    Promise.all(updates).then(() => onRefresh?.()).catch(() => onRefresh?.())
  }, [onRefresh])

  // Native drag-and-drop handlers for features dragged from backlog
  const handleNativeDragOver = useCallback((e: React.DragEvent) => {
    if (e.dataTransfer.types.includes('application/x-feature')) {
      e.preventDefault()
      e.dataTransfer.dropEffect = 'move'
      setDragOver(true)
    }
  }, [])

  const handleNativeDragLeave = useCallback(() => {
    setDragOver(false)
  }, [])

  const handleNativeDrop = useCallback((e: React.DragEvent) => {
    setDragOver(false)
    const data = e.dataTransfer.getData('application/x-feature')
    if (!data) return
    e.preventDefault()
    const { featureId, taskIds } = JSON.parse(data) as {
      featureId: string
      taskIds: string[]
    }
    onPrioritizeFeature?.(featureId, taskIds)
  }, [onPrioritizeFeature])

  return (
    <div
      className={`column prioritized-column${isOver || dragOver ? ' column-drop-target' : ''}`}
      onDragOver={handleNativeDragOver}
      onDragLeave={handleNativeDragLeave}
      onDrop={handleNativeDrop}
    >
      <div className="column-header">
        <span className="column-dot col-prioritized" />
        <span className="column-title">Prioritized</span>
        <span className="column-count">{tasks.length}</span>
      </div>
      <div className="prioritized-content" ref={setNodeRef}>
        {orderedGroups.length === 0 && (
          <div className="prioritized-empty">
            Drag features here from the backlog
          </div>
        )}
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          modifiers={[restrictToVerticalAxis]}
          onDragEnd={handleFeatureReorder}
        >
          <SortableContext
            items={orderedGroups.map(g => g.featureId)}
            strategy={verticalListSortingStrategy}
          >
            {orderedGroups.map(group => (
              <SortableFeatureGroup key={group.featureId} group={group} onItemClick={onItemClick} onDeprioritize={() => deprioritizeFeature(group)}>
                <div className="prioritized-feature">
                  <DndContext
                    sensors={sensors}
                    collisionDetection={closestCenter}
                    modifiers={[restrictToVerticalAxis]}
                    onDragEnd={(event) => handleTaskReorder(group.featureId, event)}
                  >
                    <SortableContext
                      items={group.tasks.map(t => t.id)}
                      strategy={verticalListSortingStrategy}
                    >
                      <div className="prioritized-tasks-list">
                        {group.tasks.map(task => (
                          <SortableItem key={task.id} id={task.id}>
                            <div
                              className="prioritized-task"
                              onClick={() => onTaskClick(task.id)}
                            >
                              {task.number > 0 && (
                                <span className="entity-number">
                                  {formatEntityNumber('task', task.number)}{' '}
                                </span>
                              )}
                              {task.title}
                            </div>
                          </SortableItem>
                        ))}
                      </div>
                    </SortableContext>
                  </DndContext>
                </div>
              </SortableFeatureGroup>
            ))}
          </SortableContext>
        </DndContext>
      </div>
    </div>
  )
}

function SortableFeatureGroup({ group, onItemClick, onDeprioritize, children }: {
  group: FeatureGroup
  onItemClick: (type: 'epic' | 'feature' | 'task', id: string) => void
  onDeprioritize: () => void
  children: React.ReactNode
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: group.featureId })
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  }

  return (
    <div ref={setNodeRef} style={style}>
      <div
        className="prioritized-feature-header"
        style={{ borderLeftColor: group.epicColor }}
      >
        <span
          className="deprioritize-handle"
          title="Drag to reorder or drag to Backlog"
          {...attributes}
          {...listeners}
        >
          &#x2630;
        </span>
        <span
          className="prioritized-feature-title"
          onClick={() => onItemClick('feature', group.featureId)}
        >
          {group.featureNumber > 0 && (
            <span className="entity-number">
              {formatEntityNumber('feature', group.featureNumber)}{' '}
            </span>
          )}
          {group.featureTitle}
        </span>
        <button
          className="deprioritize-btn"
          title="Move back to Backlog"
          onClick={(e) => { e.stopPropagation(); onDeprioritize() }}
        >
          &#x2715;
        </button>
      </div>
      {children}
    </div>
  )
}
