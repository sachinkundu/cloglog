import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect } from 'vitest'
import { ThemeToggle } from './ThemeToggle'

describe('ThemeToggle', () => {
  it('renders with "light" label initially (dark mode default)', () => {
    render(<ThemeToggle />)
    expect(screen.getByRole('button', { name: 'Toggle theme' })).toHaveTextContent('light')
  })

  it('toggles to "dark" label after click', async () => {
    const user = userEvent.setup()
    render(<ThemeToggle />)
    const btn = screen.getByRole('button', { name: 'Toggle theme' })

    await user.click(btn)
    expect(btn).toHaveTextContent('dark')
  })

  it('sets data-theme attribute on documentElement', async () => {
    const user = userEvent.setup()
    render(<ThemeToggle />)

    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')

    await user.click(screen.getByRole('button', { name: 'Toggle theme' }))
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
  })
})
