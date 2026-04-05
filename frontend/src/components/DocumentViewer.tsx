import { useCallback, useEffect, useRef, useState } from 'react'
import type { AnchorHTMLAttributes } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import mermaid from 'mermaid'
import { api } from '../api/client'
import type { Document } from '../api/types'
import './DocumentViewer.css'

mermaid.initialize({ startOnLoad: false, theme: 'dark' })

let mermaidCounter = 0

function MermaidDiagram({ chart }: { chart: string }) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const id = `mermaid-${++mermaidCounter}`
    mermaid.render(id, chart).then(({ svg }) => {
      if (ref.current) ref.current.innerHTML = svg
    }).catch(() => {
      if (ref.current) ref.current.textContent = chart
    })
  }, [chart])

  return <div ref={ref} className="mermaid-diagram" />
}

interface DocumentViewerProps {
  documentId: string
  onClose: () => void
}

export function DocumentViewer({ documentId, onClose }: DocumentViewerProps) {
  const [doc, setDoc] = useState<Document | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.getDocument(documentId)
      .then(setDoc)
      .catch(() => setError('Failed to load document'))
  }, [documentId])

  const renderCode = useCallback(
    (props: { className?: string; children?: React.ReactNode }) => {
      const match = /language-(\w+)/.exec(props.className ?? '')
      const lang = match?.[1]
      if (lang === 'mermaid') {
        return <MermaidDiagram chart={String(props.children).trim()} />
      }
      return (
        <code className={props.className}>
          {props.children}
        </code>
      )
    },
    []
  )

  return (
    <div className="doc-viewer-overlay" onClick={onClose}>
      <div className="doc-viewer" onClick={e => e.stopPropagation()}>
        <button className="doc-viewer-close" onClick={onClose}>x</button>
        {error && <p className="doc-viewer-error">{error}</p>}
        {!doc && !error && <p className="doc-viewer-loading">Loading...</p>}
        {doc && (
          <>
            <div className="doc-viewer-header">
              <span className={`doc-chip chip-${doc.doc_type}`}>{doc.doc_type}</span>
              <h2 className="doc-viewer-title">{doc.title}</h2>
            </div>
            <div className="doc-viewer-content">
              <Markdown remarkPlugins={[remarkGfm]} components={{ code: renderCode, a: (props: AnchorHTMLAttributes<HTMLAnchorElement>) => <a {...props} target="_blank" rel="noopener noreferrer" /> }}>{doc.content}</Markdown>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
