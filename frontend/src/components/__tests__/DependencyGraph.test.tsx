import React, { Suspense } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { Mock } from 'vitest'
import { DependencyGraph } from '../DependencyGraph'
import type { DependencyGraphResponse } from '../../api/types'

// Mock heavy Excalidraw modules before any imports that might trigger them
vi.mock('@excalidraw/excalidraw', () => ({
  Excalidraw: (_props: Record<string, unknown>) => <div data-testid="excalidraw-canvas" />,
  convertToExcalidrawElements: (elements: unknown[]) => elements,
}))

vi.mock('@excalidraw/mermaid-to-excalidraw', () => ({
  parseMermaidToExcalidraw: vi.fn().mockResolvedValue({
    elements: [{ type: 'rectangle', id: 'test' }],
    files: {},
  }),
}))

vi.mock('@excalidraw/excalidraw/index.css', () => ({}))
vi.mock('../DependencyGraph.css', () => ({}))

// Mock the API client
vi.mock('../../api/client', () => ({
  api: {
    getDependencyGraph: vi.fn(),
    streamUrl: vi.fn().mockReturnValue('http://localhost/stream'),
  },
}))

// Mock EventSource globally (for useSSE hook)
vi.stubGlobal('EventSource', class MockEventSource {
  addEventListener() {}
  removeEventListener() {}
  close() {}
  set onerror(_: unknown) {}
})

// Import after mocks
import { api } from '../../api/client'
import { parseMermaidToExcalidraw } from '@excalidraw/mermaid-to-excalidraw'

const mockGetDependencyGraph = api.getDependencyGraph as Mock
const mockParseMermaid = parseMermaidToExcalidraw as Mock

const emptyGraph: DependencyGraphResponse = { nodes: [], edges: [] }

const singleNodeGraph: DependencyGraphResponse = {
  nodes: [
    {
      id: 'feat-uuid-1',
      number: 1,
      title: 'Auth System',
      status: 'in_progress',
      epic_title: 'Platform',
      epic_color: '#7c3aed',
    },
  ],
  edges: [],
}

const multiNodeGraph: DependencyGraphResponse = {
  nodes: [
    {
      id: 'feat-uuid-1',
      number: 1,
      title: 'Auth System',
      status: 'done',
      epic_title: 'Platform',
      epic_color: '#7c3aed',
    },
    {
      id: 'feat-uuid-2',
      number: 2,
      title: 'User Dashboard',
      status: 'backlog',
      epic_title: 'UI',
      epic_color: '#2563eb',
    },
  ],
  edges: [
    { from_id: 'feat-uuid-1', to_id: 'feat-uuid-2', from_number: 1, to_number: 2 },
  ],
}

function renderDependencyGraph(props?: Partial<React.ComponentProps<typeof DependencyGraph>>) {
  const defaultProps = {
    projectId: 'proj-1',
    onItemClick: vi.fn(),
    ...props,
  }
  return render(
    <MemoryRouter>
      <Suspense fallback={<div>Loading...</div>}>
        <DependencyGraph {...defaultProps} />
      </Suspense>
    </MemoryRouter>
  )
}

describe('DependencyGraph', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockParseMermaid.mockResolvedValue({
      elements: [{ type: 'rectangle', id: 'test' }],
      files: {},
    })
  })

  describe('loading state', () => {
    it('shows loading message while graph is being fetched', async () => {
      // Never resolve to keep loading state
      mockGetDependencyGraph.mockReturnValue(new Promise(() => {}))

      renderDependencyGraph()

      await waitFor(() => {
        expect(screen.getByText('loading dependency graph...')).toBeInTheDocument()
      })
    })
  })

  describe('empty state', () => {
    it('shows empty state when graph has no nodes', async () => {
      mockGetDependencyGraph.mockResolvedValue(emptyGraph)

      renderDependencyGraph()

      await waitFor(() => {
        expect(screen.getByText('No features yet')).toBeInTheDocument()
      })
    })

    it('does not render excalidraw canvas when graph is empty', async () => {
      mockGetDependencyGraph.mockResolvedValue(emptyGraph)

      renderDependencyGraph()

      await waitFor(() => {
        expect(screen.queryByTestId('excalidraw-canvas')).not.toBeInTheDocument()
      })
    })
  })

  describe('graph rendering', () => {
    it('renders the excalidraw canvas when graph data exists', async () => {
      mockGetDependencyGraph.mockResolvedValue(singleNodeGraph)

      renderDependencyGraph()

      await waitFor(() => {
        expect(screen.getByTestId('excalidraw-canvas')).toBeInTheDocument()
      })
    })

    it('calls parseMermaidToExcalidraw when nodes are present', async () => {
      mockGetDependencyGraph.mockResolvedValue(singleNodeGraph)

      renderDependencyGraph()

      await waitFor(() => {
        expect(mockParseMermaid).toHaveBeenCalledOnce()
      })
    })

    it('passes a mermaid definition containing node numbers to parseMermaidToExcalidraw', async () => {
      mockGetDependencyGraph.mockResolvedValue(singleNodeGraph)

      renderDependencyGraph()

      await waitFor(() => {
        expect(mockParseMermaid).toHaveBeenCalledWith(
          expect.stringContaining('F1')
        )
      })
    })

    it('renders excalidraw canvas for multi-node graph with edges', async () => {
      mockGetDependencyGraph.mockResolvedValue(multiNodeGraph)

      renderDependencyGraph()

      await waitFor(() => {
        expect(screen.getByTestId('excalidraw-canvas')).toBeInTheDocument()
      })
    })
  })

  describe('mermaid definition generation (via parseMermaidToExcalidraw calls)', () => {
    it('generates flowchart LR definition', async () => {
      mockGetDependencyGraph.mockResolvedValue(singleNodeGraph)

      renderDependencyGraph()

      await waitFor(() => {
        const mermaidDef = mockParseMermaid.mock.calls[0][0] as string
        expect(mermaidDef).toContain('flowchart LR')
      })
    })

    it('wraps nodes in epic subgraphs', async () => {
      mockGetDependencyGraph.mockResolvedValue(singleNodeGraph)

      renderDependencyGraph()

      await waitFor(() => {
        const mermaidDef = mockParseMermaid.mock.calls[0][0] as string
        expect(mermaidDef).toContain('subgraph')
        expect(mermaidDef).toContain('Platform')
      })
    })

    it('assigns correct status class — done', async () => {
      const doneGraph: DependencyGraphResponse = {
        nodes: [{ id: 'f1', number: 1, title: 'Done Feature', status: 'done', epic_title: 'Epic', epic_color: '#000' }],
        edges: [],
      }
      mockGetDependencyGraph.mockResolvedValue(doneGraph)

      renderDependencyGraph()

      await waitFor(() => {
        const mermaidDef = mockParseMermaid.mock.calls[0][0] as string
        expect(mermaidDef).toContain(':::done')
      })
    })

    it('assigns correct status class — in_progress', async () => {
      const inProgressGraph: DependencyGraphResponse = {
        nodes: [{ id: 'f1', number: 1, title: 'Active Feature', status: 'in_progress', epic_title: 'Epic', epic_color: '#000' }],
        edges: [],
      }
      mockGetDependencyGraph.mockResolvedValue(inProgressGraph)

      renderDependencyGraph()

      await waitFor(() => {
        const mermaidDef = mockParseMermaid.mock.calls[0][0] as string
        expect(mermaidDef).toContain(':::in_progress')
      })
    })

    it('assigns correct status class — review maps to in_progress', async () => {
      const reviewGraph: DependencyGraphResponse = {
        nodes: [{ id: 'f1', number: 1, title: 'Review Feature', status: 'review', epic_title: 'Epic', epic_color: '#000' }],
        edges: [],
      }
      mockGetDependencyGraph.mockResolvedValue(reviewGraph)

      renderDependencyGraph()

      await waitFor(() => {
        const mermaidDef = mockParseMermaid.mock.calls[0][0] as string
        expect(mermaidDef).toContain(':::in_progress')
      })
    })

    it('assigns planned class for backlog status', async () => {
      const backlogGraph: DependencyGraphResponse = {
        nodes: [{ id: 'f1', number: 1, title: 'Planned Feature', status: 'backlog', epic_title: 'Epic', epic_color: '#000' }],
        edges: [],
      }
      mockGetDependencyGraph.mockResolvedValue(backlogGraph)

      renderDependencyGraph()

      await waitFor(() => {
        const mermaidDef = mockParseMermaid.mock.calls[0][0] as string
        expect(mermaidDef).toContain(':::planned')
      })
    })

    it('includes edge arrows between dependent features', async () => {
      mockGetDependencyGraph.mockResolvedValue(multiNodeGraph)

      renderDependencyGraph()

      await waitFor(() => {
        const mermaidDef = mockParseMermaid.mock.calls[0][0] as string
        expect(mermaidDef).toContain('F1 --> F2')
      })
    })

    it('escapes double quotes in epic titles', async () => {
      const quotedGraph: DependencyGraphResponse = {
        nodes: [{ id: 'f1', number: 1, title: 'Feature', status: 'backlog', epic_title: 'Epic "One"', epic_color: '#000' }],
        edges: [],
      }
      mockGetDependencyGraph.mockResolvedValue(quotedGraph)

      renderDependencyGraph()

      await waitFor(() => {
        const mermaidDef = mockParseMermaid.mock.calls[0][0] as string
        // The quotes should be escaped as #quot; in the mermaid definition
        expect(mermaidDef).not.toContain('"One"')
        expect(mermaidDef).toContain('#quot;One#quot;')
      })
    })

    it('includes classDef definitions in the mermaid output', async () => {
      mockGetDependencyGraph.mockResolvedValue(singleNodeGraph)

      renderDependencyGraph()

      await waitFor(() => {
        const mermaidDef = mockParseMermaid.mock.calls[0][0] as string
        expect(mermaidDef).toContain('classDef done')
        expect(mermaidDef).toContain('classDef in_progress')
        expect(mermaidDef).toContain('classDef planned')
      })
    })

    it('adds click handler links for feature navigation', async () => {
      mockGetDependencyGraph.mockResolvedValue(singleNodeGraph)

      renderDependencyGraph()

      await waitFor(() => {
        const mermaidDef = mockParseMermaid.mock.calls[0][0] as string
        expect(mermaidDef).toContain(`click F1 "/features/feat-uuid-1"`)
      })
    })
  })

  describe('error state', () => {
    it('shows error message when mermaid parsing fails', async () => {
      mockGetDependencyGraph.mockResolvedValue(singleNodeGraph)
      mockParseMermaid.mockRejectedValue(new Error('Parse failed'))

      renderDependencyGraph()

      await waitFor(() => {
        expect(screen.getByText('Failed to render graph')).toBeInTheDocument()
      })
    })

    it('does not render excalidraw when parsing fails', async () => {
      mockGetDependencyGraph.mockResolvedValue(singleNodeGraph)
      mockParseMermaid.mockRejectedValue(new Error('Parse error'))

      renderDependencyGraph()

      await waitFor(() => {
        expect(screen.queryByTestId('excalidraw-canvas')).not.toBeInTheDocument()
      })
    })
  })

  describe('multiple epics', () => {
    it('generates separate subgraphs for nodes in different epics', async () => {
      mockGetDependencyGraph.mockResolvedValue(multiNodeGraph)

      renderDependencyGraph()

      await waitFor(() => {
        const mermaidDef = mockParseMermaid.mock.calls[0][0] as string
        expect(mermaidDef).toContain('Platform')
        expect(mermaidDef).toContain('UI')
        // Two subgraphs — E0 and E1
        expect(mermaidDef).toContain('subgraph E0')
        expect(mermaidDef).toContain('subgraph E1')
      })
    })

    it('applies epic stroke color to subgraph style', async () => {
      mockGetDependencyGraph.mockResolvedValue(singleNodeGraph)

      renderDependencyGraph()

      await waitFor(() => {
        const mermaidDef = mockParseMermaid.mock.calls[0][0] as string
        expect(mermaidDef).toContain('stroke:#7c3aed')
      })
    })
  })
})
