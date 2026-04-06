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
import { TaskCard } from './TaskCard'
import './Board.css'

interface BoardProps {
  board: BoardResponse
  backlog: BacklogEpic[]
  projectId: string
  onTaskClick: (taskId: string) => void
  onItemClick: (type: 'epic' | 'feature' | 'task', id: string) => void
  onRefresh?: () => void
}

export function Board({ board, backlog, projectId, onTaskClick, onItemClick, onRefresh }: BoardProps) {
  const flowColumns = board.columns.filter(col => col.status !== 'backlog')
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

    // Optimistically update via API, then refresh
    api.updateTask(task.id, { status: targetStatus })
      .then(() => onRefresh?.())
      .catch(() => onRefresh?.())
  }, [onRefresh])

  const handleDragCancel = useCallback(() => {
    setActiveTask(null)
  }, [])

  return (
    <div className="board">
      <BoardHeader board={board} projectId={projectId} onItemClick={onItemClick} />
      <div className="board-columns">
        <div className="board-backlog">
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
        <DndContext
          sensors={sensors}
          onDragStart={handleDragStart}
          onDragEnd={handleDragEnd}
          onDragCancel={handleDragCancel}
        >
          {flowColumns.map(col => (
            <Column key={col.status} column={col} onTaskClick={onTaskClick} onRefresh={onRefresh} draggable />
          ))}
          <DragOverlay>
            {activeTask ? (
              <div className="drag-overlay-card">
                <TaskCard task={activeTask} onClick={() => {}} />
              </div>
            ) : null}
          </DragOverlay>
        </DndContext>
      </div>
    </div>
  )
}
