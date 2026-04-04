import { describe, it, expect } from 'vitest'
import { formatEntityNumber } from './format'

describe('formatEntityNumber', () => {
  it('formats epic numbers', () => {
    expect(formatEntityNumber('epic', 1)).toBe('E-1')
    expect(formatEntityNumber('epic', 12)).toBe('E-12')
  })

  it('formats feature numbers', () => {
    expect(formatEntityNumber('feature', 3)).toBe('F-3')
  })

  it('formats task numbers', () => {
    expect(formatEntityNumber('task', 37)).toBe('T-37')
  })

  it('returns empty string for number 0', () => {
    expect(formatEntityNumber('task', 0)).toBe('')
  })
})
