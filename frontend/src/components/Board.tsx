import { useCallback } from 'react'
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  TouchSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from '@dnd-kit/core'
import { useState } from 'react'
import type { BacklogEpic, BoardResponse, TaskCard as TaskCardType } from '../api/types'
import { api } from '../api/client'
import { BacklogTree } from './BacklogTree'
import { BoardHeader } from './BoardHeader'
import { Column } from './Column'
import { PrioritizedColumn } from './PrioritizedColumn'
import { TaskCard } from './TaskCard'
import './Board.css'

interface BoardProps {
  board: BoardResponse
  backlog: BacklogEpic[]
  projectId: string
  onTaskClick: (taskId: string) => void
  onItemClick: (type: 'epic' | 'feature' | 'task', id: string) => void
  onRefresh?: () => void
  onMoveTask?: (taskId: string, newStatus: string) => void
  worktreeNames?: Record<string, string>
  agentFilter?: string | null
}

export function Board({ board, backlog, projectId, onTaskClick, onItemClick, onRefresh, onMoveTask, worktreeNames, agentFilter }: BoardProps) {
  const flowColumns = board.columns.filter(col => col.status !== 'backlog' && col.status !== 'prioritized')
  const prioritizedColumn = board.columns.find(col => col.status === 'prioritized')
  const [activeTask, setActiveTask] = useState<TaskCardType | null>(null)

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 200, tolerance: 5 } }),
  )

  const handleReorderEpics = useCallback((items: { id: string; position: number }[]) => {
    api.reorderEpics(projectId, items).catch(() => onRefresh?.())
  }, [projectId, onRefresh])

  const handleReorderFeatures = useCallback((epicId: string, items: { id: string; position: number }[]) => {
    api.reorderFeatures(projectId, epicId, items).catch(() => onRefresh?.())
  }, [projectId, onRefresh])

  const handleReorderTasks = useCallback((featureId: string, items: { id: string; position: number }[]) => {
    api.reorderTasks(featureId, items).catch(() => onRefresh?.())
  }, [onRefresh])

  const handlePrioritizeFeature = useCallback((featureId: string, taskIds: string[]) => {
    const updates: Promise<unknown>[] = taskIds.map(id =>
      api.updateTask(id, { status: 'prioritized' })
    )
    // Also mark the feature itself as prioritized so taskless features show up
    updates.push(api.updateFeature(featureId, { status: 'prioritized' }))
    Promise.all(updates).then(() => onRefresh?.()).catch(() => onRefresh?.())
  }, [onRefresh])

  const handleDragStart = useCallback((event: DragStartEvent) => {
    const task = event.active.data.current?.task as TaskCardType | undefined
    if (task) setActiveTask(task)
  }, [])

  const handleDragEnd = useCallback((event: DragEndEvent) => {
    setActiveTask(null)
    const { active, over } = event
    if (!over) return

    const task = active.data.current?.task as TaskCardType | undefined
    if (!task) return

    // Extract status from the droppable column id (format: "column-<status>")
    const targetStatus = over.data.current?.status as string | undefined
    if (!targetStatus || targetStatus === task.status) return

    // Optimistic local move — no full refetch needed
    onMoveTask?.(task.id, targetStatus)

    // Persist to backend; only refetch on failure to restore correct state
    api.updateTask(task.id, { status: targetStatus })
      .then(() => {
        // User-initiated drag to review: dismiss the auto-notification
        // so it doesn't alert the user about their own action
        if (targetStatus === 'review') {
          api.dismissTaskNotification(projectId, task.id).catch(() => {})
        }
      })
      .catch(() => onRefresh?.())
  }, [onMoveTask, onRefresh, projectId])

  const handleDragCancel = useCallback(() => {
    setActiveTask(null)
  }, [])

  const [backlogDragOver, setBacklogDragOver] = useState(false)

  const handleDeprioritize = useCallback((featureId: string, taskIds: string[]) => {
    const updates: Promise<unknown>[] = taskIds.map(id =>
      api.updateTask(id, { status: 'backlog' })
    )
    updates.push(api.updateFeature(featureId, { status: 'planned' }))
    Promise.all(updates).then(() => onRefresh?.()).catch(() => onRefresh?.())
  }, [onRefresh])

  return (
    <div className="board">
      <BoardHeader board={board} projectId={projectId} onItemClick={onItemClick} />
      <div className="board-columns">
        <div
          className={`board-backlog${backlogDragOver ? ' column-drop-target' : ''}`}
          onDragOver={(e) => {
            if (e.dataTransfer.types.includes('application/x-deprioritize')) {
              e.preventDefault()
              e.dataTransfer.dropEffect = 'move'
              setBacklogDragOver(true)
            }
          }}
          onDragLeave={() => setBacklogDragOver(false)}
          onDrop={(e) => {
            setBacklogDragOver(false)
            const data = e.dataTransfer.getData('application/x-deprioritize')
            if (!data) return
            e.preventDefault()
            const { featureId, taskIds } = JSON.parse(data) as { featureId: string; taskIds: string[] }
            handleDeprioritize(featureId, taskIds)
          }}
        >
          <div className="column-header">
            <span className="column-dot col-backlog" />
            <span className="column-title">Backlog</span>
            <span className="column-count">
              {board.columns.find(c => c.status === 'backlog')?.tasks.length ?? 0}
            </span>
          </div>
          <BacklogTree
            backlog={backlog}
            onItemClick={onItemClick}
            onReorderEpics={handleReorderEpics}
            onReorderFeatures={handleReorderFeatures}
            onReorderTasks={handleReorderTasks}
          />
        </div>
        {prioritizedColumn && (
          <PrioritizedColumn
            tasks={prioritizedColumn.tasks}
            backlog={backlog}
            onTaskClick={onTaskClick}
            onItemClick={onItemClick}
            onRefresh={onRefresh}
            onMoveTask={onMoveTask}
            onPrioritizeFeature={handlePrioritizeFeature}
          />
        )}
        <DndContext
          sensors={sensors}
          onDragStart={handleDragStart}
          onDragEnd={handleDragEnd}
          onDragCancel={handleDragCancel}
        >
          {flowColumns.map(col => (
            <Column key={col.status} column={col} projectId={projectId} onTaskClick={onTaskClick} onRefresh={onRefresh} draggable worktreeNames={worktreeNames} agentFilter={agentFilter} />
          ))}
          <DragOverlay>
            {activeTask ? (
              <div className="drag-overlay-card">
                <TaskCard task={activeTask} onClick={() => {}} worktreeNames={worktreeNames} />
              </div>
            ) : null}
          </DragOverlay>
        </DndContext>
      </div>
    </div>
  )
}
