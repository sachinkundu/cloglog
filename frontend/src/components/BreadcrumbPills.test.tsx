import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { BreadcrumbPills } from './BreadcrumbPills'

describe('BreadcrumbPills', () => {
  it('renders epic and feature pills', () => {
    render(
      <BreadcrumbPills epicTitle="Auth System" featureTitle="OAuth" epicColor="#7c3aed" />
    )
    expect(screen.getByText('Auth System')).toBeInTheDocument()
    expect(screen.getByText('OAuth')).toBeInTheDocument()
  })

  it('renders only epic pill when no feature title', () => {
    render(
      <BreadcrumbPills epicTitle="Auth System" featureTitle="" epicColor="#7c3aed" />
    )
    expect(screen.getByText('Auth System')).toBeInTheDocument()
  })

  it('applies epic color as CSS variable', () => {
    const { container } = render(
      <BreadcrumbPills epicTitle="Auth" featureTitle="OAuth" epicColor="#7c3aed" />
    )
    const epicPill = container.querySelector('.pill-epic')
    expect(epicPill).toBeTruthy()
  })
})
