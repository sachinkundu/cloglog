export class HeartbeatTimer {
  private intervalId: ReturnType<typeof setInterval> | null = null
  private callback: () => Promise<void>
  private intervalMs: number

  constructor(callback: () => Promise<void>, intervalMs: number = 60_000) {
    this.callback = callback
    this.intervalMs = intervalMs
  }

  start(): void {
    this.stop()
    this.intervalId = setInterval(async () => {
      try {
        await this.callback()
      } catch (err) {
        console.error('Heartbeat failed:', err)
      }
    }, this.intervalMs)
  }

  stop(): void {
    if (this.intervalId !== null) {
      clearInterval(this.intervalId)
      this.intervalId = null
    }
  }
}
