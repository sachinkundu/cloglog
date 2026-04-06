import { useDraggable } from '@dnd-kit/core'
import { CSS } from '@dnd-kit/utilities'
import type { TaskCard as TaskCardType } from '../api/types'
import { TaskCard } from './TaskCard'

interface DraggableTaskCardProps {
  task: TaskCardType
  onClick: () => void
}

export function DraggableTaskCard({ task, onClick }: DraggableTaskCardProps) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: task.id,
    data: { task },
  })

  const style = {
    transform: CSS.Transform.toString(transform),
    opacity: isDragging ? 0.5 : 1,
    cursor: 'grab',
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...listeners}
      {...attributes}
    >
      <TaskCard task={task} onClick={onClick} />
    </div>
  )
}
