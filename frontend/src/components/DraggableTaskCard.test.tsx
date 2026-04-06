import { render, screen } from '@testing-library/react'
import { DndContext } from '@dnd-kit/core'
import { describe, it, expect, vi } from 'vitest'
import { DraggableTaskCard } from './DraggableTaskCard'
import type { TaskCard as TaskCardType } from '../api/types'

const makeTask = (overrides?: Partial<TaskCardType>): TaskCardType => ({
  id: 't1',
  feature_id: 'f1',
  title: 'Test Task',
  description: '',
  status: 'in_progress',
  priority: 'normal',
  task_type: 'task',
  pr_url: null,
  worktree_id: null,
  position: 0,
  number: 1,
  archived: false,
  created_at: '',
  updated_at: '',
  epic_title: 'Epic A',
  feature_title: 'Feature A',
  epic_color: '#7c3aed',
  ...overrides,
})

describe('DraggableTaskCard', () => {
  it('renders the task card within a DndContext', () => {
    render(
      <DndContext>
        <DraggableTaskCard task={makeTask()} onClick={vi.fn()} />
      </DndContext>
    )
    expect(screen.getByText('Test Task')).toBeInTheDocument()
  })

  it('renders expedite priority badge', () => {
    render(
      <DndContext>
        <DraggableTaskCard task={makeTask({ priority: 'expedite' })} onClick={vi.fn()} />
      </DndContext>
    )
    expect(screen.getByText('expedite')).toBeInTheDocument()
  })

  it('renders with grab cursor style', () => {
    const { container } = render(
      <DndContext>
        <DraggableTaskCard task={makeTask()} onClick={vi.fn()} />
      </DndContext>
    )
    const draggable = container.firstElementChild as HTMLElement
    expect(draggable.style.cursor).toBe('grab')
  })
})
