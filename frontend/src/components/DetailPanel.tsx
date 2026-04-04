import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { DocumentSummary } from '../api/types'
import { BreadcrumbPills } from './BreadcrumbPills'
import { DocumentViewer } from './DocumentViewer'
import { formatEntityNumber } from '../utils/format'
import './DetailPanel.css'

interface EpicData {
  id: string
  title: string
  description: string
  color: string
  bounded_context: string
  task_counts: { total: number; done: number }
  features: Array<{ title: string; task_counts: { total: number; done: number } }>
  number?: number
}

interface FeatureData {
  id: string
  title: string
  description: string
  epic: { title: string; id: string; color: string }
  task_counts: { total: number; done: number }
  tasks: Array<{ id: string; title: string; status: string }>
  number?: number
}

interface TaskData {
  title: string
  description: string
  status: string
  priority: string
  epic: { title: string; id: string; color: string }
  feature: { title: string; id: string }
  worktree_id: string | null
  number?: number
}

type DetailPanelProps = {
  onClose: () => void
  onNavigate: (type: 'epic' | 'feature' | 'task', id: string) => void
} & (
  | { type: 'epic'; data: EpicData }
  | { type: 'feature'; data: FeatureData }
  | { type: 'task'; data: TaskData }
)

export function DetailPanel({ type, data, onClose, onNavigate }: DetailPanelProps) {
  return (
    <div className="detail-overlay" data-testid="detail-overlay" onClick={onClose}>
      <div className="detail-panel" onClick={e => e.stopPropagation()}>
        <button className="detail-close" onClick={onClose}>x</button>

        {type === 'epic' && <EpicDetail data={data as EpicData} />}
        {type === 'feature' && <FeatureDetail data={data as FeatureData} onNavigate={onNavigate} />}
        {type === 'task' && <TaskDetail data={data as TaskData} onNavigate={onNavigate} />}
      </div>
    </div>
  )
}

function ProgressBar({ done, total }: { done: number; total: number }) {
  const pct = total === 0 ? 0 : Math.round((done / total) * 100)
  return (
    <div className="detail-progress">
      <div className="detail-progress-bar">
        <div className="detail-progress-fill" style={{ width: `${pct}%` }} />
      </div>
      <span className="detail-progress-text">{done}/{total} tasks ({pct}%)</span>
    </div>
  )
}

function useDocuments(entityType: 'epic' | 'feature', entityId: string) {
  const [docs, setDocs] = useState<DocumentSummary[]>([])
  useEffect(() => {
    const fetcher = entityType === 'epic'
      ? api.getEpicDocuments(entityId)
      : api.getFeatureDocuments(entityId)
    fetcher.then(setDocs).catch(() => {})
  }, [entityType, entityId])
  return docs
}

function DocumentChips({ docs }: { docs: DocumentSummary[] }) {
  const [viewingDocId, setViewingDocId] = useState<string | null>(null)
  if (docs.length === 0) return null
  return (
    <div className="detail-section">
      <h3>Documents</h3>
      <div className="doc-chips">
        {docs.map(doc => (
          <button
            key={doc.id}
            className={`doc-chip chip-${doc.doc_type}`}
            onClick={() => setViewingDocId(doc.id)}
          >
            {doc.doc_type}: {doc.title}
          </button>
        ))}
      </div>
      {viewingDocId && (
        <DocumentViewer
          documentId={viewingDocId}
          onClose={() => setViewingDocId(null)}
        />
      )}
    </div>
  )
}

function EpicDetail({ data }: { data: EpicData }) {
  const docs = useDocuments('epic', data.id)
  return (
    <>
      <div className="detail-header" style={{ borderLeftColor: data.color }}>
        <h2 className="detail-title">
          {data.number != null && data.number > 0 && <span className="entity-number">{formatEntityNumber('epic', data.number)} </span>}
          {data.title}
        </h2>
        {data.bounded_context && (
          <span className="detail-badge">{data.bounded_context}</span>
        )}
      </div>
      <ProgressBar done={data.task_counts.done} total={data.task_counts.total} />
      {data.description && <p className="detail-description">{data.description}</p>}
      <DocumentChips docs={docs} />
      {data.features.length > 0 && (
        <div className="detail-section">
          <h3>Features</h3>
          {data.features.map((f, i) => (
            <div key={i} className="detail-list-item">
              <span>{f.title}</span>
              <span className="detail-count">{f.task_counts.done}/{f.task_counts.total}</span>
            </div>
          ))}
        </div>
      )}
    </>
  )
}

function FeatureDetail({ data, onNavigate }: { data: FeatureData; onNavigate: (type: 'epic' | 'feature' | 'task', id: string) => void }) {
  const docs = useDocuments('feature', data.id)
  return (
    <>
      <div className="detail-header">
        <span
          className="detail-parent-pill"
          style={{ background: `color-mix(in srgb, ${data.epic.color} 20%, transparent)`, color: data.epic.color }}
          onClick={() => onNavigate('epic', data.epic.id)}
        >
          {data.epic.title}
        </span>
        <h2 className="detail-title">
          {data.number != null && data.number > 0 && <span className="entity-number">{formatEntityNumber('feature', data.number)} </span>}
          {data.title}
        </h2>
      </div>
      <ProgressBar done={data.task_counts.done} total={data.task_counts.total} />
      {data.description && <p className="detail-description">{data.description}</p>}
      <DocumentChips docs={docs} />
      {data.tasks.length > 0 && (
        <div className="detail-section">
          <h3>Tasks</h3>
          {data.tasks.map(t => (
            <div key={t.id} className="detail-list-item" onClick={() => onNavigate('task', t.id)}>
              <span>{t.title}</span>
              <span className={`detail-status status-${t.status}`}>{t.status}</span>
            </div>
          ))}
        </div>
      )}
    </>
  )
}

function TaskDetail({ data, onNavigate }: { data: TaskData; onNavigate: (type: 'epic' | 'feature' | 'task', id: string) => void }) {
  return (
    <>
      <div className="detail-header">
        <BreadcrumbPills
          epicTitle={data.epic.title}
          featureTitle={data.feature.title}
          epicColor={data.epic.color}
          onEpicClick={() => onNavigate('epic', data.epic.id)}
          onFeatureClick={() => onNavigate('feature', data.feature.id)}
        />
        <h2 className="detail-title">
          {data.number != null && data.number > 0 && <span className="entity-number">{formatEntityNumber('task', data.number)} </span>}
          {data.title}
        </h2>
        <div className="detail-meta">
          <span className={`detail-status status-${data.status}`}>{data.status}</span>
          {data.priority === 'expedite' && <span className="detail-badge expedite">expedite</span>}
          {data.worktree_id && <span className="detail-agent">agent assigned</span>}
        </div>
      </div>
      {data.description && <p className="detail-description">{data.description}</p>}
    </>
  )
}
