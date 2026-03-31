import { describe, it, expect } from 'vitest'
import { CloglogClient } from '../src/client.js'

describe('CloglogClient', () => {
  it('constructs with config', () => {
    const client = new CloglogClient({
      baseUrl: 'http://localhost:8000',
      apiKey: 'test-key',
    })
    expect(client).toBeTruthy()
  })

  it('strips trailing slash from base URL', () => {
    const client = new CloglogClient({
      baseUrl: 'http://localhost:8000/',
      apiKey: 'test-key',
    })
    // Access private field for verification via any cast
    expect((client as any).baseUrl).toBe('http://localhost:8000')
  })
})
