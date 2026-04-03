import { render, screen } from '@testing-library/react'
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

describe('BoardHeader', () => {
  it('renders project name', () => {
    render(<BoardHeader board={makeBoard(10, 3)} />)
    expect(screen.getByText('My Project')).toBeInTheDocument()
  })

  it('renders task count and done count', () => {
    render(<BoardHeader board={makeBoard(10, 3)} />)
    expect(screen.getByText(/10 tasks/)).toBeInTheDocument()
    expect(screen.getByText(/3 done/)).toBeInTheDocument()
  })

  it('calculates percentage correctly', () => {
    render(<BoardHeader board={makeBoard(10, 3)} />)
    expect(screen.getByText(/30%/)).toBeInTheDocument()
  })

  it('shows 0% when there are no tasks', () => {
    render(<BoardHeader board={makeBoard(0, 0)} />)
    expect(screen.getByText(/0%/)).toBeInTheDocument()
  })

  it('rounds percentage', () => {
    render(<BoardHeader board={makeBoard(3, 1)} />)
    expect(screen.getByText(/33%/)).toBeInTheDocument()
  })
})
