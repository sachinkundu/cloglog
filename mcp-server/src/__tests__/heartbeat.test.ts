import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { HeartbeatTimer } from '../heartbeat.js'

describe('HeartbeatTimer', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('calls the callback at the specified interval', async () => {
    const callback = vi.fn().mockResolvedValue(undefined)
    const timer = new HeartbeatTimer(callback, 60_000)
    timer.start()

    await vi.advanceTimersByTimeAsync(60_000)
    expect(callback).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(60_000)
    expect(callback).toHaveBeenCalledTimes(2)

    timer.stop()
  })

  it('stops calling after stop()', async () => {
    const callback = vi.fn().mockResolvedValue(undefined)
    const timer = new HeartbeatTimer(callback, 60_000)
    timer.start()

    await vi.advanceTimersByTimeAsync(60_000)
    expect(callback).toHaveBeenCalledTimes(1)

    timer.stop()

    await vi.advanceTimersByTimeAsync(120_000)
    expect(callback).toHaveBeenCalledTimes(1)
  })

  it('does not crash if callback throws', async () => {
    const callback = vi.fn().mockRejectedValue(new Error('network error'))
    const timer = new HeartbeatTimer(callback, 60_000)
    timer.start()

    await vi.advanceTimersByTimeAsync(60_000)
    expect(callback).toHaveBeenCalledTimes(1)

    // Timer should continue despite error
    await vi.advanceTimersByTimeAsync(60_000)
    expect(callback).toHaveBeenCalledTimes(2)

    timer.stop()
  })
})
