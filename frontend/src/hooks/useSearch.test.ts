import { renderHook, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

vi.mock('../api/client', () => ({
  api: {
    search: vi.fn(),
  },
}))

import { useSearch } from './useSearch'
import { api } from '../api/client'

const mockSearch = vi.mocked(api.search)

describe('useSearch', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns empty results initially', () => {
    const { result } = renderHook(() => useSearch('p1'))

    expect(result.current.results).toEqual([])
    expect(result.current.loading).toBe(false)
    expect(result.current.parsed).toBeNull()
  })

  it('empty query clears results without API call', () => {
    const { result } = renderHook(() => useSearch('p1'))

    act(() => {
      result.current.search('  ')
    })

    expect(mockSearch).not.toHaveBeenCalled()
    expect(result.current.results).toEqual([])
    expect(result.current.loading).toBe(false)
  })

  it('debounces API calls by 200ms', async () => {
    const mockResults = {
      query: 'test',
      results: [{ id: 'r1', type: 'task' as const, title: 'Test Task', number: 1, status: 'backlog' }],
      total: 1,
    }
    mockSearch.mockResolvedValue(mockResults)

    const { result } = renderHook(() => useSearch('p1'))

    act(() => {
      result.current.search('test')
    })

    // Not called yet — still within debounce window
    expect(mockSearch).not.toHaveBeenCalled()
    expect(result.current.loading).toBe(true)

    // Advance past debounce
    await act(async () => {
      vi.advanceTimersByTime(200)
    })

    expect(mockSearch).toHaveBeenCalledTimes(1)
    expect(mockSearch).toHaveBeenCalledWith('p1', 'test', 20, expect.any(AbortSignal), null)
    expect(result.current.results).toEqual(mockResults.results)
    expect(result.current.loading).toBe(false)
  })

  it('aborts previous request on new search', async () => {
    mockSearch.mockImplementation((_pid, _q, _limit, signal) => {
      return new Promise((resolve, reject) => {
        signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
        // Never resolves naturally — only via abort
      })
    })

    const { result } = renderHook(() => useSearch('p1'))

    act(() => {
      result.current.search('first')
    })

    await act(async () => {
      vi.advanceTimersByTime(200)
    })

    expect(mockSearch).toHaveBeenCalledTimes(1)

    // Second search should abort first
    act(() => {
      result.current.search('second')
    })

    await act(async () => {
      vi.advanceTimersByTime(200)
    })

    expect(mockSearch).toHaveBeenCalledTimes(2)
  })

  it('sets loading true while fetching', () => {
    mockSearch.mockReturnValue(new Promise(() => {})) // never resolves

    const { result } = renderHook(() => useSearch('p1'))

    act(() => {
      result.current.search('hello')
    })

    expect(result.current.loading).toBe(true)
  })

  it('clear resets results and cancels pending', async () => {
    const mockResults = {
      query: 'test',
      results: [{ id: 'r1', type: 'task' as const, title: 'Test', number: 1, status: 'backlog' }],
      total: 1,
    }
    mockSearch.mockResolvedValue(mockResults)

    const { result } = renderHook(() => useSearch('p1'))

    // Search and get results
    act(() => {
      result.current.search('test')
    })
    await act(async () => {
      vi.advanceTimersByTime(200)
    })
    expect(result.current.results).toHaveLength(1)

    // Clear
    act(() => {
      result.current.clear()
    })

    expect(result.current.results).toEqual([])
    expect(result.current.loading).toBe(false)
    expect(result.current.parsed).toBeNull()
  })

  it('passes status_filter when is:open qualifier is used', async () => {
    const mockResults = {
      query: 'agent',
      results: [{ id: 'r1', type: 'task' as const, title: 'Agent Task', number: 1, status: 'backlog' }],
      total: 1,
    }
    mockSearch.mockResolvedValue(mockResults)

    const { result } = renderHook(() => useSearch('p1'))

    act(() => {
      result.current.search('is:open agent')
    })

    await act(async () => {
      vi.advanceTimersByTime(200)
    })

    expect(mockSearch).toHaveBeenCalledTimes(1)
    expect(mockSearch).toHaveBeenCalledWith(
      'p1',
      'agent',
      20,
      expect.any(AbortSignal),
      expect.arrayContaining(['backlog', 'in_progress', 'review']),
    )
    expect(result.current.parsed?.statusFilter).toEqual(
      expect.arrayContaining(['backlog', 'in_progress', 'review']),
    )
  })

  it('passes status_filter when is:closed qualifier is used', async () => {
    const mockResults = {
      query: 'migration',
      results: [],
      total: 0,
    }
    mockSearch.mockResolvedValue(mockResults)

    const { result } = renderHook(() => useSearch('p1'))

    act(() => {
      result.current.search('is:closed migration')
    })

    await act(async () => {
      vi.advanceTimersByTime(200)
    })

    expect(mockSearch).toHaveBeenCalledWith(
      'p1',
      'migration',
      20,
      expect.any(AbortSignal),
      ['done'],
    )
  })

  it('qualifier-only query does not call API (no text)', () => {
    const { result } = renderHook(() => useSearch('p1'))

    act(() => {
      result.current.search('is:open')
    })

    expect(mockSearch).not.toHaveBeenCalled()
    // But parsed state is still set
    expect(result.current.parsed?.statusFilter).toEqual(
      expect.arrayContaining(['backlog', 'in_progress', 'review']),
    )
  })
})
