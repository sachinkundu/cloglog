import { renderHook } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useSSE } from './useSSE'

// Mock EventSource
class MockEventSource {
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  readyState = 0
  url: string
  close = vi.fn()

  constructor(url: string) {
    this.url = url
    MockEventSource.instances.push(this)
  }

  addEventListener(type: string, handler: (event: MessageEvent) => void) {
    // Store handlers by event type
    if (!this._handlers[type]) this._handlers[type] = []
    this._handlers[type].push(handler)
  }

  removeEventListener() {}

  _handlers: Record<string, Array<(event: MessageEvent) => void>> = {}
  static instances: MockEventSource[] = []
  static reset() { MockEventSource.instances = [] }
}

beforeEach(() => {
  MockEventSource.reset()
  vi.stubGlobal('EventSource', MockEventSource)
})

describe('useSSE', () => {
  it('connects to the correct URL', () => {
    renderHook(() => useSSE('project-123', vi.fn()))
    expect(MockEventSource.instances).toHaveLength(1)
    expect(MockEventSource.instances[0].url).toContain('project-123')
  })

  it('closes connection on unmount', () => {
    const { unmount } = renderHook(() => useSSE('project-123', vi.fn()))
    unmount()
    expect(MockEventSource.instances[0].close).toHaveBeenCalled()
  })
})
