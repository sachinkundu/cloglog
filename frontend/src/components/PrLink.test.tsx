import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import { PrLink } from './PrLink'

describe('PrLink', () => {
  it('renders PR number extracted from GitHub URL', () => {
    render(<PrLink url="https://github.com/sachinkundu/cloglog/pull/45" />)
    expect(screen.getByText('PR #45')).toBeInTheDocument()
  })

  it('renders generic "PR" label when URL has no pull number', () => {
    render(<PrLink url="https://github.com/sachinkundu/cloglog/issues/10" />)
    expect(screen.getByText('PR')).toBeInTheDocument()
  })

  it('links to the PR URL with target _blank', () => {
    render(<PrLink url="https://github.com/sachinkundu/cloglog/pull/99" />)
    const link = screen.getByRole('link')
    expect(link).toHaveAttribute('href', 'https://github.com/sachinkundu/cloglog/pull/99')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('stops click propagation so card onClick is not triggered', async () => {
    const parentClick = vi.fn()
    const user = userEvent.setup()
    render(
      <div onClick={parentClick}>
        <PrLink url="https://github.com/sachinkundu/cloglog/pull/1" />
      </div>
    )
    await user.click(screen.getByRole('link'))
    expect(parentClick).not.toHaveBeenCalled()
  })

  it('shows the full URL as tooltip', () => {
    const url = 'https://github.com/sachinkundu/cloglog/pull/123'
    render(<PrLink url={url} />)
    expect(screen.getByRole('link')).toHaveAttribute('title', url)
  })
})
