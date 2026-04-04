const PREFIXES: Record<string, string> = {
  epic: 'E',
  feature: 'F',
  task: 'T',
}

export function formatEntityNumber(type: string, number: number): string {
  if (number === 0) return ''
  const prefix = PREFIXES[type] ?? '?'
  return `${prefix}-${number}`
}
