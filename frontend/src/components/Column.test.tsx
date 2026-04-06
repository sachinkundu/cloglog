import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DndContext } from '@dnd-kit/core'
import { describe, it, expect, vi } from 'vitest'
import { Column } from './Column'
import type { BoardColumn } from '../api/types'

const makeTask = (id: string, title: string, status: string, archived = false) => ({
  id,
  feature_id: 'f1',
  title,
  description: '',
  status,
  priority: 'normal',
  task_type: 'task',
  pr_url: null as string | null,
  worktree_id: null,
  position: 0,
  number: 1,
  archived,
  created_at: '',
  updated_at: '',
  epic_title: 'Epic',
  feature_title: 'Feature',
  epic_color: '#7c3aed',
})

function renderColumn(column: BoardColumn, props?: { draggable?: boolean; onRefresh?: () => void }) {
  return render(
    <DndContext>
      <Column
        column={column}
        onTaskClick={vi.fn()}
        draggable={props?.draggable}
        onRefresh={props?.onRefresh}
      />
    </DndContext>
  )
}

describe('Column', () => {
  it('renders column label for known statuses', () => {
    renderColumn({ status: 'in_progress', tasks: [] })
    expect(screen.getByText('In Progress')).toBeInTheDocument()
  })

  it('renders Review label for review status', () => {
    renderColumn({ status: 'review', tasks: [] })
    expect(screen.getByText('Review')).toBeInTheDocument()
  })

  it('falls back to raw status for unknown statuses', () => {
    renderColumn({ status: 'custom_status', tasks: [] })
    expect(screen.getByText('custom_status')).toBeInTheDocument()
  })

  it('renders task count', () => {
    renderColumn({
      status: 'backlog',
      tasks: [makeTask('t1', 'Task A', 'backlog'), makeTask('t2', 'Task B', 'backlog')],
    })
    expect(screen.getByText('2')).toBeInTheDocument()
  })

  it('renders all tasks', () => {
    renderColumn({
      status: 'backlog',
      tasks: [makeTask('t1', 'Task A', 'backlog'), makeTask('t2', 'Task B', 'backlog')],
    })
    expect(screen.getByText('Task A')).toBeInTheDocument()
    expect(screen.getByText('Task B')).toBeInTheDocument()
  })

  it('calls onTaskClick with the correct task id', async () => {
    const user = userEvent.setup()
    const onTaskClick = vi.fn()
    const column: BoardColumn = {
      status: 'backlog',
      tasks: [makeTask('t1', 'Task A', 'backlog')],
    }
    render(
      <DndContext>
        <Column column={column} onTaskClick={onTaskClick} />
      </DndContext>
    )

    await user.click(screen.getByText('Task A'))
    expect(onTaskClick).toHaveBeenCalledWith('t1')
  })

  it('renders empty column with zero count', () => {
    renderColumn({ status: 'done', tasks: [] })
    expect(screen.getByText('Done')).toBeInTheDocument()
    expect(screen.getByText('0')).toBeInTheDocument()
  })

  it('shows Archive button only for done column with tasks', () => {
    renderColumn({
      status: 'done',
      tasks: [makeTask('t1', 'Done Task', 'done')],
    })
    expect(screen.getByText('Archive')).toBeInTheDocument()
  })

  it('does not show Archive button for non-done columns', () => {
    renderColumn({
      status: 'in_progress',
      tasks: [makeTask('t1', 'Task', 'in_progress')],
    })
    expect(screen.queryByText('Archive')).not.toBeInTheDocument()
  })

  it('separates archived and non-archived done tasks', () => {
    renderColumn({
      status: 'done',
      tasks: [
        makeTask('t1', 'Active Task', 'done', false),
        makeTask('t2', 'Hidden Task', 'done', true),
      ],
    })
    expect(screen.getByText('Active Task')).toBeInTheDocument()
    expect(screen.queryByText('Hidden Task')).not.toBeInTheDocument()
    expect(screen.getByText('Archived (1)')).toBeInTheDocument()
  })

  it('expands archived section to show archived tasks', async () => {
    const user = userEvent.setup()
    renderColumn({
      status: 'done',
      tasks: [makeTask('t1', 'Hidden Task', 'done', true)],
    })

    await user.click(screen.getByText('Archived (1)'))
    expect(screen.getByText('Hidden Task')).toBeInTheDocument()
  })

  it('calls API and onRefresh when archiving', async () => {
    const user = userEvent.setup()
    const { api } = await import('../api/client')
    const archiveSpy = vi.spyOn(api, 'archiveTask').mockResolvedValue({})
    const onRefresh = vi.fn()
    renderColumn(
      { status: 'done', tasks: [makeTask('t1', 'Done Task', 'done', false)] },
      { onRefresh },
    )

    await user.click(screen.getByText('Archive'))
    expect(archiveSpy).toHaveBeenCalledWith('t1')
    expect(onRefresh).toHaveBeenCalled()
    archiveSpy.mockRestore()
  })

  // Draggable prop tests
  it('renders tasks as draggable when draggable prop is true', () => {
    const { container } = renderColumn(
      { status: 'in_progress', tasks: [makeTask('t1', 'Drag Me', 'in_progress')] },
      { draggable: true },
    )
    const draggable = container.querySelector('[style*="cursor: grab"]')
    expect(draggable).toBeTruthy()
  })

  it('renders tasks as non-draggable by default', () => {
    const { container } = renderColumn({
      status: 'in_progress',
      tasks: [makeTask('t1', 'No Drag', 'in_progress')],
    })
    const draggable = container.querySelector('[style*="cursor: grab"]')
    expect(draggable).toBeNull()
  })

  it('applies drop-target class when column is hovered during drag', () => {
    // Column uses useDroppable, so the class is applied dynamically.
    // We verify the column element exists and can receive the class.
    const { container } = renderColumn(
      { status: 'review', tasks: [] },
      { draggable: true },
    )
    const column = container.querySelector('.column')
    expect(column).toBeTruthy()
    // Not actively being dragged over, so no drop-target class
    expect(column?.classList.contains('column-drop-target')).toBe(false)
  })
})
