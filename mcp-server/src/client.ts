/**
 * HTTP client for the cloglog API.
 * Each MCP tool calls methods on this client.
 */

export interface CloglogClientConfig {
  baseUrl: string
  apiKey: string
}

export class CloglogClient {
  private baseUrl: string
  private apiKey: string

  constructor(config: CloglogClientConfig) {
    this.baseUrl = config.baseUrl.replace(/\/$/, '')
    this.apiKey = config.apiKey
  }

  async request(method: string, path: string, body?: unknown): Promise<unknown> {
    const url = `${this.baseUrl}${path}`
    const headers: Record<string, string> = {
      'Authorization': `Bearer ${this.apiKey}`,
      'Content-Type': 'application/json',
    }

    const response = await fetch(url, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    })

    if (!response.ok) {
      const text = await response.text()
      throw new Error(`cloglog API error: ${response.status} ${text}`)
    }

    return response.json()
  }
}
