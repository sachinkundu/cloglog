import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { SearchWidget } from './SearchWidget'
import type { SearchResult } from '../api/types'

import type { ParsedQuery } from '../lib/searchQualifiers'

const mockSearch = vi.fn()
const mockClear = vi.fn()
let mockResults: SearchResult[] = []
let mockLoading = false
let mockParsed: ParsedQuery | null = null

vi.mock('../hooks/useSearch', () => ({
  useSearch: () => ({
    results: mockResults,
    loading: mockLoading,
    parsed: mockParsed,
    search: mockSearch,
    clear: mockClear,
  }),
}))

const makeResult = (overrides: Partial<SearchResult> = {}): SearchResult => ({
  id: 't1',
  type: 'task',
  title: 'Build login page',
  number: 42,
  status: 'in_progress',
  epic_color: '#7c3aed',
  feature_title: 'Auth Feature',
  ...overrides,
})

// jsdom doesn't implement scrollIntoView
Element.prototype.scrollIntoView = vi.fn()

describe('SearchWidget', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockResults = []
    mockLoading = false
    mockParsed = null
  })

  it('renders search input with placeholder', () => {
    render(<SearchWidget projectId="p1" onSelect={vi.fn()} />)

    const input = screen.getByTestId('search-input')
    expect(input).toBeInTheDocument()
    expect(input).toHaveAttribute('placeholder', 'Search epics, features, tasks...')
  })

  it('typing calls search function', async () => {
    const user = userEvent.setup()
    render(<SearchWidget projectId="p1" onSelect={vi.fn()} />)

    const input = screen.getByTestId('search-input')
    await user.type(input, 'hello')

    expect(mockSearch).toHaveBeenCalled()
    // Called once per keystroke
    expect(mockSearch).toHaveBeenCalledTimes(5)
  })

  it('displays results when available', async () => {
    mockResults = [
      makeResult({ id: 't1', title: 'Build login page', number: 42 }),
      makeResult({ id: 'f1', type: 'feature', title: 'Auth Feature', number: 5, epic_title: 'Platform' }),
    ]
    const user = userEvent.setup()
    render(<SearchWidget projectId="p1" onSelect={vi.fn()} />)

    // Focus and type to open dropdown
    const input = screen.getByTestId('search-input')
    await user.type(input, 'test')

    expect(screen.getByTestId('search-dropdown')).toBeInTheDocument()
    const resultElements = screen.getAllByTestId('search-result')
    expect(resultElements).toHaveLength(2)
    expect(screen.getByText('Build login page')).toBeInTheDocument()
    expect(screen.getByText('T-42')).toBeInTheDocument()
    expect(screen.getByText('F-5')).toBeInTheDocument()
  })

  it('clicking result calls onSelect', async () => {
    const onSelect = vi.fn()
    mockResults = [makeResult({ id: 't1', type: 'task', title: 'Test Task', number: 10 })]
    const user = userEvent.setup()
    render(<SearchWidget projectId="p1" onSelect={onSelect} />)

    const input = screen.getByTestId('search-input')
    await user.type(input, 'test')

    const result = screen.getByTestId('search-result')
    await user.click(result)

    expect(onSelect).toHaveBeenCalledWith('task', 't1')
  })

  it('arrow down moves highlight', async () => {
    mockResults = [
      makeResult({ id: 't1', title: 'First', number: 1 }),
      makeResult({ id: 't2', title: 'Second', number: 2 }),
    ]
    const user = userEvent.setup()
    render(<SearchWidget projectId="p1" onSelect={vi.fn()} />)

    const input = screen.getByTestId('search-input')
    await user.type(input, 'test')

    await user.keyboard('{ArrowDown}')
    const resultElements = screen.getAllByTestId('search-result')
    expect(resultElements[0]).toHaveClass('highlighted')

    await user.keyboard('{ArrowDown}')
    expect(resultElements[1]).toHaveClass('highlighted')
    expect(resultElements[0]).not.toHaveClass('highlighted')
  })

  it('enter selects highlighted result', async () => {
    const onSelect = vi.fn()
    mockResults = [
      makeResult({ id: 't1', type: 'task', title: 'First', number: 1 }),
      makeResult({ id: 't2', type: 'feature', title: 'Second', number: 2 }),
    ]
    const user = userEvent.setup()
    render(<SearchWidget projectId="p1" onSelect={onSelect} />)

    const input = screen.getByTestId('search-input')
    await user.type(input, 'test')

    await user.keyboard('{ArrowDown}')
    await user.keyboard('{Enter}')

    expect(onSelect).toHaveBeenCalledWith('task', 't1')
  })

  it('escape clears input', async () => {
    mockResults = [makeResult()]
    const user = userEvent.setup()
    render(<SearchWidget projectId="p1" onSelect={vi.fn()} />)

    const input = screen.getByTestId('search-input')
    await user.type(input, 'test')

    await user.keyboard('{Escape}')

    expect(input).toHaveValue('')
    expect(mockClear).toHaveBeenCalled()
  })

  it('Cmd+K focuses input', () => {
    render(<SearchWidget projectId="p1" onSelect={vi.fn()} />)

    const input = screen.getByTestId('search-input')
    expect(document.activeElement).not.toBe(input)

    fireEvent.keyDown(document, { key: 'k', metaKey: true })

    expect(document.activeElement).toBe(input)
  })

  it('shows loading state', async () => {
    mockLoading = true
    mockResults = []
    const user = userEvent.setup()
    render(<SearchWidget projectId="p1" onSelect={vi.fn()} />)

    const input = screen.getByTestId('search-input')
    await user.type(input, 'test')

    expect(screen.getByTestId('search-loading')).toBeInTheDocument()
    expect(screen.getByText('Searching...')).toBeInTheDocument()
  })

  it('shows shortcut hint when input is empty and unfocused', () => {
    render(<SearchWidget projectId="p1" onSelect={vi.fn()} />)

    expect(screen.getByTestId('search-hint')).toBeInTheDocument()
  })

  it('shows breadcrumb for tasks and features', async () => {
    mockResults = [
      makeResult({ id: 't1', type: 'task', title: 'Task', number: 1, feature_title: 'My Feature' }),
      makeResult({ id: 'f1', type: 'feature', title: 'Feature', number: 2, epic_title: 'My Epic' }),
    ]
    const user = userEvent.setup()
    render(<SearchWidget projectId="p1" onSelect={vi.fn()} />)

    const input = screen.getByTestId('search-input')
    await user.type(input, 'test')

    expect(screen.getByText('My Feature')).toBeInTheDocument()
    expect(screen.getByText('My Epic')).toBeInTheDocument()
  })

  it('shows filter pill when is:open qualifier is active', () => {
    mockParsed = { text: 'agent', statusFilter: ['backlog', 'in_progress', 'review'] }
    render(<SearchWidget projectId="p1" onSelect={vi.fn()} />)

    const pill = screen.getByTestId('search-filter-pill')
    expect(pill).toBeInTheDocument()
    expect(pill).toHaveTextContent('open')
  })

  it('shows filter pill for is:closed qualifier', () => {
    mockParsed = { text: 'migration', statusFilter: ['done'] }
    render(<SearchWidget projectId="p1" onSelect={vi.fn()} />)

    const pill = screen.getByTestId('search-filter-pill')
    expect(pill).toHaveTextContent('closed')
  })

  it('shows filter pill for is:archived qualifier', () => {
    mockParsed = { text: 'old', statusFilter: ['archived'] }
    render(<SearchWidget projectId="p1" onSelect={vi.fn()} />)

    const pill = screen.getByTestId('search-filter-pill')
    expect(pill).toHaveTextContent('archived')
  })

  it('does not show filter pill when no qualifier active', () => {
    mockParsed = null
    render(<SearchWidget projectId="p1" onSelect={vi.fn()} />)

    expect(screen.queryByTestId('search-filter-pill')).not.toBeInTheDocument()
  })
})
