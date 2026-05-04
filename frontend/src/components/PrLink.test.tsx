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

  it('shows merged badge when merged is true', () => {
    render(<PrLink url="https://github.com/sachinkundu/cloglog/pull/45" merged />)
    expect(screen.getByText('Merged')).toBeInTheDocument()
    expect(screen.getByText('Merged')).toHaveClass('pr-merged-badge')
  })

  it('does not show merged badge when merged is false', () => {
    render(<PrLink url="https://github.com/sachinkundu/cloglog/pull/45" merged={false} />)
    expect(screen.queryByText('Merged')).not.toBeInTheDocument()
  })

  it('does not show merged badge when merged is not provided', () => {
    render(<PrLink url="https://github.com/sachinkundu/cloglog/pull/45" />)
    expect(screen.queryByText('Merged')).not.toBeInTheDocument()
  })

  // --- codex status badge tests (T-409) ---

  it('shows no codex badge when codexStatus is null', () => {
    render(<PrLink url="https://github.com/o/r/pull/1" codexStatus={null} />)
    expect(screen.queryByText(/codex/i)).not.toBeInTheDocument()
  })

  it('shows no codex badge when codexStatus is not_started', () => {
    render(<PrLink url="https://github.com/o/r/pull/1" codexStatus="not_started" />)
    expect(screen.queryByText(/codex/i)).not.toBeInTheDocument()
  })

  it('shows animated "codex working" badge with pulse class', () => {
    render(<PrLink url="https://github.com/o/r/pull/1" codexStatus="working" />)
    const badge = screen.getByText('codex working')
    expect(badge).toBeInTheDocument()
    expect(badge).toHaveClass('pr-codex-badge--working')
  })

  it('shows "codex N/M" progress badge', () => {
    render(
      <PrLink
        url="https://github.com/o/r/pull/1"
        codexStatus="progress"
        codexProgress={{ turn: 2, max_turns: 3, sha: 'abc123' }}
      />
    )
    const badge = screen.getByText('codex 2/3')
    expect(badge).toBeInTheDocument()
    expect(badge).toHaveClass('pr-codex-badge--progress')
  })

  it('shows "codex pass" badge in green class', () => {
    render(<PrLink url="https://github.com/o/r/pull/1" codexStatus="pass" />)
    const badge = screen.getByText('codex pass')
    expect(badge).toBeInTheDocument()
    expect(badge).toHaveClass('pr-codex-badge--pass')
  })

  it('shows "codex exhausted" badge in red class', () => {
    render(<PrLink url="https://github.com/o/r/pull/1" codexStatus="exhausted" />)
    const badge = screen.getByText('codex exhausted')
    expect(badge).toBeInTheDocument()
    expect(badge).toHaveClass('pr-codex-badge--exhausted')
  })

  it('shows "codex failed" badge in red class', () => {
    render(<PrLink url="https://github.com/o/r/pull/1" codexStatus="failed" />)
    const badge = screen.getByText('codex failed')
    expect(badge).toBeInTheDocument()
    expect(badge).toHaveClass('pr-codex-badge--failed')
  })

  it('shows "codex stale" badge in amber class', () => {
    render(<PrLink url="https://github.com/o/r/pull/1" codexStatus="stale" />)
    const badge = screen.getByText('codex stale')
    expect(badge).toBeInTheDocument()
    expect(badge).toHaveClass('pr-codex-badge--stale')
  })

  it('badge title includes sha for progress state', () => {
    render(
      <PrLink
        url="https://github.com/o/r/pull/1"
        codexStatus="progress"
        codexProgress={{ turn: 1, max_turns: 2, sha: 'deadbeef1234567' }}
      />
    )
    const badge = screen.getByText('codex 1/2')
    expect(badge).toHaveAttribute('title', 'codex 1/2 (deadbee)')
  })

  it('falls back to "pass" appearance when deprecated codexReviewed=true with no codexStatus', () => {
    render(<PrLink url="https://github.com/o/r/pull/1" codexReviewed={true} />)
    const badge = screen.getByText('codex pass')
    expect(badge).toBeInTheDocument()
  })

  it('shows no badge when deprecated codexReviewed=false with no codexStatus', () => {
    render(<PrLink url="https://github.com/o/r/pull/1" codexReviewed={false} />)
    expect(screen.queryByText(/codex/i)).not.toBeInTheDocument()
  })
})
