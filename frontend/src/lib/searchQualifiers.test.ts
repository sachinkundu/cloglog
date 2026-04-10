import { describe, it, expect } from 'vitest'
import { parseSearchQualifiers } from './searchQualifiers'

describe('parseSearchQualifiers', () => {
  it('returns null statusFilter when no qualifiers present', () => {
    const result = parseSearchQualifiers('hello world')
    expect(result.text).toBe('hello world')
    expect(result.statusFilter).toBeNull()
  })

  it('parses is:open into backlog, in_progress, review', () => {
    const result = parseSearchQualifiers('is:open agent')
    expect(result.text).toBe('agent')
    expect(result.statusFilter).toEqual(
      expect.arrayContaining(['backlog', 'in_progress', 'review']),
    )
    expect(result.statusFilter).toHaveLength(3)
  })

  it('parses is:closed into done', () => {
    const result = parseSearchQualifiers('is:closed migration')
    expect(result.text).toBe('migration')
    expect(result.statusFilter).toEqual(['done'])
  })

  it('parses is:archived', () => {
    const result = parseSearchQualifiers('is:archived old task')
    expect(result.text).toBe('old task')
    expect(result.statusFilter).toEqual(['archived'])
  })

  it('handles qualifier with no text', () => {
    const result = parseSearchQualifiers('is:open')
    expect(result.text).toBe('')
    expect(result.statusFilter).toEqual(
      expect.arrayContaining(['backlog', 'in_progress', 'review']),
    )
  })

  it('handles multiple qualifiers', () => {
    const result = parseSearchQualifiers('is:open is:closed search term')
    expect(result.text).toBe('search term')
    expect(result.statusFilter).toEqual(
      expect.arrayContaining(['backlog', 'in_progress', 'review', 'done']),
    )
  })

  it('is case-insensitive', () => {
    const result = parseSearchQualifiers('IS:Open test')
    expect(result.text).toBe('test')
    expect(result.statusFilter).toEqual(
      expect.arrayContaining(['backlog', 'in_progress', 'review']),
    )
  })

  it('handles qualifier in middle of text', () => {
    const result = parseSearchQualifiers('find is:closed tasks')
    expect(result.text).toBe('find tasks')
    expect(result.statusFilter).toEqual(['done'])
  })

  it('normalizes whitespace after removing qualifiers', () => {
    const result = parseSearchQualifiers('  is:open   agent  ')
    expect(result.text).toBe('agent')
  })
})
