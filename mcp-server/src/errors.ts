/**
 * Typed errors raised by the cloglog HTTP client. Preserving the JSON
 * ``detail`` on 4xx/5xx responses lets MCP tool handlers switch on
 * ``code`` (e.g. ``task_blocked``) and render structured payloads as
 * readable tool output instead of flattening them to a raw string.
 */

export interface StructuredDetail {
  code?: string
  message?: string
  blockers?: Array<Record<string, unknown>>
  [key: string]: unknown
}

export type ErrorDetail = string | StructuredDetail

export class CloglogApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: ErrorDetail,
  ) {
    const msg =
      typeof detail === 'string'
        ? `cloglog API error: ${status} ${detail}`
        : `cloglog API error: ${status} ${detail.message ?? JSON.stringify(detail)}`
    super(msg)
    this.name = 'CloglogApiError'
  }

  get code(): string | undefined {
    return typeof this.detail === 'object' ? this.detail.code : undefined
  }

  /**
   * The structured detail if the server returned one, else `undefined`.
   * Callers that need to switch on ``code`` or render ``blockers`` should
   * check this first.
   */
  get structured(): StructuredDetail | undefined {
    return typeof this.detail === 'object' ? this.detail : undefined
  }
}
