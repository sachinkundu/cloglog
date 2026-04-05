import React, { Suspense, useEffect, useState } from 'react'
import { convertToExcalidrawElements } from '@excalidraw/excalidraw'
import { parseMermaidToExcalidraw } from '@excalidraw/mermaid-to-excalidraw'
import '@excalidraw/excalidraw/index.css'
import { useDependencyGraph } from '../hooks/useDependencyGraph'
import type { DependencyGraphNode, DependencyGraphEdge } from '../api/types'
import './DependencyGraph.css'

const ExcalidrawLazy = React.lazy(() =>
  import('@excalidraw/excalidraw').then(mod => ({ default: mod.Excalidraw }))
)

interface DependencyGraphProps {
  projectId: string
  onItemClick: (type: 'epic' | 'feature' | 'task', id: string) => void
}

function buildMermaidDef(nodes: DependencyGraphNode[], edges: DependencyGraphEdge[]): string {
  // Group nodes by epic
  const epicGroups = new Map<string, { color: string; nodes: DependencyGraphNode[] }>()
  for (const node of nodes) {
    const key = node.epic_title
    if (!epicGroups.has(key)) {
      epicGroups.set(key, { color: node.epic_color, nodes: [] })
    }
    epicGroups.get(key)!.nodes.push(node)
  }

  let def = 'flowchart LR\n'
  let epicIdx = 0
  for (const [epicTitle, group] of epicGroups) {
    const safeTitle = epicTitle.replace(/"/g, '#quot;')
    def += `  subgraph E${epicIdx}["${safeTitle}"]\n`
    def += `    style E${epicIdx} fill:transparent,stroke:${group.color}\n`
    for (const node of group.nodes) {
      const safeNodeTitle = node.title.replace(/"/g, '#quot;')
      const statusClass = node.status === 'done' ? 'done'
        : ['in_progress', 'review'].includes(node.status) ? 'in_progress'
        : 'planned'
      def += `    F${node.number}["F-${node.number} ${safeNodeTitle}"]:::${statusClass}\n`
      def += `    click F${node.number} "/features/${node.id}"\n`
    }
    def += '  end\n'
    epicIdx++
  }

  for (const edge of edges) {
    def += `  F${edge.from_number} --> F${edge.to_number}\n`
  }

  def += '\n  classDef done fill:#059669,stroke:#047857,color:#fff\n'
  def += '  classDef in_progress fill:#2563eb,stroke:#1d4ed8,color:#fff\n'
  def += '  classDef planned fill:#374151,stroke:#4b5563,color:#d1d5db\n'

  return def
}

export function DependencyGraph({ projectId, onItemClick }: DependencyGraphProps) {
  const { graph, loading } = useDependencyGraph(projectId)
  const [excalidrawElements, setExcalidrawElements] = useState<ReturnType<typeof convertToExcalidrawElements> | null>(null)
  const [files, setFiles] = useState<Record<string, unknown> | undefined>(undefined)
  const [parseError, setParseError] = useState<string | null>(null)

  useEffect(() => {
    if (!graph || graph.nodes.length === 0) {
      setExcalidrawElements(null)
      setFiles(undefined)
      return
    }

    const mermaidDef = buildMermaidDef(graph.nodes, graph.edges)

    let cancelled = false
    parseMermaidToExcalidraw(mermaidDef)
      .then(result => {
        if (cancelled) return
        const elements = convertToExcalidrawElements(result.elements)
        setExcalidrawElements(elements)
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        setFiles(result.files as any)
        setParseError(null)
      })
      .catch(err => {
        if (cancelled) return
        setParseError(String(err))
      })

    return () => { cancelled = true }
  }, [graph])

  if (loading) {
    return (
      <div className="dependency-graph">
        <div className="dependency-graph-loading">loading dependency graph...</div>
      </div>
    )
  }

  if (!graph || graph.nodes.length === 0) {
    return (
      <div className="dependency-graph">
        <div className="dependency-graph-empty">No features yet</div>
      </div>
    )
  }

  if (parseError) {
    return (
      <div className="dependency-graph">
        <div className="dependency-graph-empty">Failed to render graph</div>
      </div>
    )
  }

  const handleLinkOpen = (
    _element: { link?: string | null },
    event: CustomEvent<{ nativeEvent: MouseEvent | React.PointerEvent<HTMLCanvasElement> }>,
  ) => {
    event.preventDefault()
    const link = _element.link
    if (!link) return
    // Parse feature UUID from link like "/features/UUID"
    const match = link.match(/\/features\/([0-9a-f-]+)/)
    if (match) {
      onItemClick('feature', match[1])
    }
  }

  return (
    <div className="dependency-graph">
      <div className="dependency-graph-container">
        <Suspense fallback={<div className="dependency-graph-loading">Loading graph...</div>}>
          {excalidrawElements && (
            <ExcalidrawLazy
              initialData={{
                elements: excalidrawElements,
                files: files,
                appState: { viewBackgroundColor: 'transparent' },
              }}
              viewModeEnabled={true}
              theme="dark"
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              onLinkOpen={handleLinkOpen as any}
            />
          )}
        </Suspense>
      </div>
    </div>
  )
}
