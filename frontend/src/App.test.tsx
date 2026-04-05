import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi } from 'vitest'
import App from './App'

// Mock the API
vi.mock('./api/client', () => ({
  api: {
    listProjects: vi.fn().mockResolvedValue([]),
    getBoard: vi.fn().mockResolvedValue(null),
    getWorktrees: vi.fn().mockResolvedValue([]),
    getDependencyGraph: vi.fn().mockResolvedValue({ nodes: [], edges: [] }),
    streamUrl: vi.fn().mockReturnValue('http://test/stream'),
  },
}))

// Mock EventSource
vi.stubGlobal('EventSource', class {
  addEventListener() {}
  removeEventListener() {}
  close() {}
  set onerror(_: unknown) {}
})

describe('App', () => {
  it('renders the sidebar title', () => {
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>
    )
    expect(screen.getByText('cloglog')).toBeInTheDocument()
  })

  it('shows select prompt when no project selected', async () => {
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>
    )
    expect(await screen.findByText('select a project')).toBeInTheDocument()
  })
})
