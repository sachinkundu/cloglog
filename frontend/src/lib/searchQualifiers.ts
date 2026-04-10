/**
 * Parse GitHub-style search qualifiers from a search query string.
 *
 * Supported qualifiers:
 *   is:open    — backlog, in_progress, review
 *   is:closed  — done
 *   is:archived — archived items (archived flag)
 *
 * Returns the remaining text query and an array of status filters.
 */

const STATUS_MAP: Record<string, string[]> = {
  open: ['backlog', 'in_progress', 'review'],
  closed: ['done'],
}

export interface ParsedQuery {
  /** The text portion of the query with qualifiers removed */
  text: string
  /** Status values to filter by, or null if no is: qualifier was used */
  statusFilter: string[] | null
}

const QUALIFIER_RE = /\bis:(open|closed|archived)\b/gi

export function parseSearchQualifiers(raw: string): ParsedQuery {
  const statuses = new Set<string>()
  let hasQualifier = false

  const text = raw
    .replace(QUALIFIER_RE, (_match, value: string) => {
      hasQualifier = true
      const key = value.toLowerCase()
      const mapped = STATUS_MAP[key]
      if (mapped) {
        for (const s of mapped) statuses.add(s)
      }
      // 'archived' is handled differently — we still pass it as a status
      // even though the backend model uses a boolean flag. The backend
      // search doesn't filter by archived yet, but this keeps the qualifier
      // parsed consistently for future use.
      if (key === 'archived') {
        statuses.add('archived')
      }
      return ''
    })
    .replace(/\s+/g, ' ')
    .trim()

  return {
    text,
    statusFilter: hasQualifier ? [...statuses] : null,
  }
}
