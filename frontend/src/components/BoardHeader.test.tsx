import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect } from 'vitest'
import { BoardHeader } from './BoardHeader'
import type { BoardResponse } from '../api/types'

const makeBoard = (total: number, done: number): BoardResponse => ({
  project_id: 'p1',
  project_name: 'My Project',
  columns: [],
  total_tasks: total,
  done_count: done,
})

function renderWithRouter(ui: React.ReactElement, path = '/projects/p1') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      {ui}
    </MemoryRouter>
  )
}

describe('BoardHeader', () => {
  it('renders project name', () => {
    renderWithRouter(<BoardHeader board={makeBoard(10, 3)} projectId="p1" />)
    expect(screen.getByText('My Project')).toBeInTheDocument()
  })

  it('renders task count and done count', () => {
    renderWithRouter(<BoardHeader board={makeBoard(10, 3)} projectId="p1" />)
    expect(screen.getByText(/10 tasks/)).toBeInTheDocument()
    expect(screen.getByText(/3 done/)).toBeInTheDocument()
  })

  it('calculates percentage correctly', () => {
    renderWithRouter(<BoardHeader board={makeBoard(10, 3)} projectId="p1" />)
    expect(screen.getByText(/30%/)).toBeInTheDocument()
  })

  it('shows 0% when there are no tasks', () => {
    renderWithRouter(<BoardHeader board={makeBoard(0, 0)} projectId="p1" />)
    expect(screen.getByText(/0%/)).toBeInTheDocument()
  })

  it('rounds percentage', () => {
    renderWithRouter(<BoardHeader board={makeBoard(3, 1)} projectId="p1" />)
    expect(screen.getByText(/33%/)).toBeInTheDocument()
  })

  it('renders Board and Dependencies tab buttons', () => {
    renderWithRouter(<BoardHeader board={makeBoard(10, 3)} projectId="p1" />)
    expect(screen.getByText('Board')).toBeInTheDocument()
    expect(screen.getByText('Dependencies')).toBeInTheDocument()
  })
})
