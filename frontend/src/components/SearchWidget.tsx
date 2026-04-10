import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearch } from '../hooks/useSearch'
import type { SearchResult } from '../api/types'
import type { ParsedQuery } from '../lib/searchQualifiers'
import './SearchWidget.css'

interface SearchWidgetProps {
  projectId: string
  onSelect: (type: 'epic' | 'feature' | 'task', id: string) => void
}

function entityPrefix(type: SearchResult['type']): string {
  switch (type) {
    case 'epic': return 'E-'
    case 'feature': return 'F-'
    case 'task': return 'T-'
  }
}

function breadcrumb(result: SearchResult): string | undefined {
  if (result.type === 'task') return result.feature_title
  if (result.type === 'feature') return result.epic_title
  return undefined
}

function filterLabel(parsed: ParsedQuery): string | null {
  if (!parsed.statusFilter) return null
  const filters = parsed.statusFilter
  if (
    filters.length === 3 &&
    filters.includes('backlog') &&
    filters.includes('in_progress') &&
    filters.includes('review')
  ) {
    return 'open'
  }
  if (filters.length === 1 && filters[0] === 'done') return 'closed'
  if (filters.length === 1 && filters[0] === 'archived') return 'archived'
  return filters.join(', ')
}

export function SearchWidget({ projectId, onSelect }: SearchWidgetProps) {
  const { results, loading, parsed, search, clear } = useSearch(projectId)
  const [inputValue, setInputValue] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(-1)
  const [focused, setFocused] = useState(false)
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const resultRefs = useRef<(HTMLDivElement | null)[]>([])

  const showDropdown = dropdownOpen && (results.length > 0 || loading)

  const handleChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value
    setInputValue(value)
    setSelectedIndex(-1)
    setDropdownOpen(true)
    search(value)
  }, [search])

  const handleSelect = useCallback((result: SearchResult) => {
    onSelect(result.type, result.id)
    setInputValue('')
    setDropdownOpen(false)
    clear()
  }, [onSelect, clear])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (!showDropdown) return

    switch (e.key) {
      case 'ArrowDown': {
        e.preventDefault()
        const next = selectedIndex < results.length - 1 ? selectedIndex + 1 : 0
        setSelectedIndex(next)
        resultRefs.current[next]?.scrollIntoView({ block: 'nearest' })
        break
      }
      case 'ArrowUp': {
        e.preventDefault()
        const prev = selectedIndex > 0 ? selectedIndex - 1 : results.length - 1
        setSelectedIndex(prev)
        resultRefs.current[prev]?.scrollIntoView({ block: 'nearest' })
        break
      }
      case 'Enter': {
        e.preventDefault()
        if (selectedIndex >= 0 && selectedIndex < results.length) {
          handleSelect(results[selectedIndex])
        }
        break
      }
      case 'Escape': {
        e.preventDefault()
        setInputValue('')
        setDropdownOpen(false)
        clear()
        inputRef.current?.blur()
        break
      }
    }
  }, [showDropdown, selectedIndex, results, handleSelect, clear])

  // Cmd+K / Ctrl+K global shortcut
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        inputRef.current?.focus()
      }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [])

  // Click outside to close
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  // Reset selected index when results change
  useEffect(() => {
    setSelectedIndex(-1)
  }, [results])

  return (
    <div className="search-widget" ref={containerRef}>
      <input
        ref={inputRef}
        type="text"
        className="search-input"
        placeholder="Search epics, features, tasks..."
        value={inputValue}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        onFocus={() => {
          setFocused(true)
          if (results.length > 0) setDropdownOpen(true)
        }}
        onBlur={() => setFocused(false)}
        data-testid="search-input"
      />
      {!focused && !inputValue && (
        <span className="search-shortcut-hint" data-testid="search-hint">⌘K</span>
      )}
      {parsed && filterLabel(parsed) && (
        <span className="search-filter-pill" data-testid="search-filter-pill">
          {filterLabel(parsed)}
        </span>
      )}
      {showDropdown && (
        <div className="search-dropdown" data-testid="search-dropdown" role="listbox">
          {loading && results.length === 0 && (
            <div className="search-loading" data-testid="search-loading">Searching...</div>
          )}
          {!loading && results.length === 0 && inputValue.trim() && (
            <div className="search-no-results">No results found</div>
          )}
          {results.map((result, i) => (
            <div
              key={result.id}
              ref={el => { resultRefs.current[i] = el }}
              className={`search-result${i === selectedIndex ? ' highlighted' : ''}`}
              role="option"
              aria-selected={i === selectedIndex}
              onClick={() => handleSelect(result)}
              data-testid="search-result"
            >
              <span
                className="search-result-dot"
                style={{ backgroundColor: result.epic_color ?? '#6b7280' }}
              />
              <span className="search-result-number">
                {entityPrefix(result.type)}{result.number}
              </span>
              <span className="search-result-title">{result.title}</span>
              {breadcrumb(result) && (
                <span className="search-result-breadcrumb">{breadcrumb(result)}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
