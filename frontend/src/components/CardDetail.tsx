import { useEffect, useState } from 'react'
import type { AnchorHTMLAttributes } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const mdComponents = {
  a: (props: AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a {...props} target="_blank" rel="noopener noreferrer" />
  ),
}
import { api } from '../api/client'
import type { Document, DocumentSummary, TaskCard } from '../api/types'
import { PrLink } from './PrLink'
import './CardDetail.css'

interface CardDetailProps {
  task: TaskCard
  onClose: () => void
}

export function CardDetail({ task, onClose }: CardDetailProps) {
  const [docs, setDocs] = useState<DocumentSummary[]>([])
  const [selectedDoc, setSelectedDoc] = useState<Document | null>(null)

  useEffect(() => {
    api.getTaskDocuments(task.id).then(setDocs).catch(() => {})
  }, [task.id])

  const openDoc = async (docId: string) => {
    const doc = await api.getDocument(docId)
    setSelectedDoc(doc)
  }

  return (
    <div className="card-detail-overlay" onClick={onClose}>
      <div className="card-detail" onClick={e => e.stopPropagation()}>
        <div className="card-detail-header">
          <div className="card-detail-breadcrumb">
            {task.epic_title} / {task.feature_title}
          </div>
          <h2 className="card-detail-title">{task.title}</h2>
          <div className="card-detail-status">
            <span className={`status-badge ${task.status}`}>{task.status}</span>
            {task.priority === 'expedite' && (
              <span className="status-badge expedite">expedite</span>
            )}
            {task.pr_url && <PrLink url={task.pr_url} />}
          </div>
          <button className="card-detail-close" onClick={onClose}>x</button>
        </div>

        {task.description && (
          <div className="card-detail-section">
            <h3>Description</h3>
            <div className="card-detail-description"><Markdown remarkPlugins={[remarkGfm]} components={mdComponents}>{task.description}</Markdown></div>
          </div>
        )}

        {docs.length > 0 && (
          <div className="card-detail-section">
            <h3>Documents</h3>
            <div className="doc-chips">
              {docs.map(doc => (
                <button
                  key={doc.id}
                  className={`doc-chip chip-${doc.doc_type}`}
                  onClick={() => openDoc(doc.id)}
                >
                  {doc.doc_type}: {doc.title}
                </button>
              ))}
            </div>
          </div>
        )}

        {selectedDoc && (
          <div className="card-detail-section">
            <h3>{selectedDoc.title}</h3>
            <pre className="doc-content">{selectedDoc.content}</pre>
          </div>
        )}
      </div>
    </div>
  )
}
