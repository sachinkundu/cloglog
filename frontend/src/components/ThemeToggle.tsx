import { useEffect, useState } from 'react'

export function ThemeToggle() {
  const [dark, setDark] = useState(true)

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light')
  }, [dark])

  return (
    <button
      onClick={() => setDark(d => !d)}
      style={{
        background: 'none',
        border: '1px solid var(--border)',
        color: 'var(--text-secondary)',
        borderRadius: 'var(--radius-sm)',
        padding: '4px 8px',
        cursor: 'pointer',
        fontFamily: 'var(--font-mono)',
        fontSize: '12px',
      }}
      aria-label="Toggle theme"
    >
      {dark ? 'light' : 'dark'}
    </button>
  )
}
