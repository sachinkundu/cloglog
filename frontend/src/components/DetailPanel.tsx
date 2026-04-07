import { useState, useEffect } from 'react'
import type { AnchorHTMLAttributes } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const mdComponents = {
  a: (props: AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a {...props} target="_blank" rel="noopener noreferrer" />
  ),
}
import { api } from '../api/client'
import type { DocumentSummary, TaskNote } from '../api/types'
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
  dependencies?: Array<{ id: string; title: string; number: number }>
  dependents?: Array<{ id: string; title: string; number: number }>
  all_features?: Array<{ id: string; title: string; number: number }>
}

interface TaskData {
  id: string
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
  projectId?: string
  worktreeNames?: Record<string, string>
} & (
  | { type: 'epic'; data: EpicData }
  | { type: 'feature'; data: FeatureData }
  | { type: 'task'; data: TaskData }
)

export function DetailPanel({ type, data, onClose, onNavigate, projectId, worktreeNames }: DetailPanelProps) {
  return (
    <div className="detail-overlay" data-testid="detail-overlay" onClick={onClose}>
      <div className="detail-panel" onClick={e => e.stopPropagation()}>
        <button className="detail-close" onClick={onClose}>x</button>

        {type === 'epic' && <EpicDetail data={data as EpicData} />}
        {type === 'feature' && <FeatureDetail data={data as FeatureData} onNavigate={onNavigate} />}
        {type === 'task' && <TaskDetail data={data as TaskData} onNavigate={onNavigate} projectId={projectId} worktreeNames={worktreeNames} />}
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
      {data.description && <div className="detail-description"><Markdown remarkPlugins={[remarkGfm]} components={mdComponents}>{data.description}</Markdown></div>}
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

function FeatureDependencies({ data, onNavigate }: { data: FeatureData; onNavigate: (type: 'epic' | 'feature' | 'task', id: string) => void }) {
  const [adding, setAdding] = useState(false)
  const [selectedId, setSelectedId] = useState('')
  const [deps, setDeps] = useState(data.dependencies ?? [])
  const [dependents] = useState(data.dependents ?? [])

  const handleRemove = async (depId: string) => {
    await api.removeDependency(data.id, depId)
    setDeps(prev => prev.filter(d => d.id !== depId))
  }

  const handleAdd = async () => {
    if (!selectedId) return
    await api.addDependency(data.id, selectedId)
    const added = data.all_features?.find(f => f.id === selectedId)
    if (added) setDeps(prev => [...prev, added])
    setAdding(false)
    setSelectedId('')
  }

  const availableFeatures = (data.all_features ?? []).filter(
    f => f.id !== data.id && !deps.some(d => d.id === f.id)
  )

  return (
    <div className="detail-section">
      <h3>Dependencies</h3>
      {deps.length > 0 && (
        <div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' }}>Depends on</div>
          {deps.map(d => (
            <div key={d.id} className="detail-list-item">
              <span onClick={() => onNavigate('feature', d.id)} style={{ cursor: 'pointer' }}>
                F-{d.number} {d.title}
              </span>
              <button
                onClick={() => handleRemove(d.id)}
                style={{
                  background: 'none', border: 'none', color: 'var(--text-muted)',
                  cursor: 'pointer', fontSize: '12px', padding: '2px 6px',
                }}
              >x</button>
            </div>
          ))}
        </div>
      )}
      {dependents.length > 0 && (
        <div style={{ marginTop: '8px' }}>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' }}>Blocks</div>
          {dependents.map(d => (
            <div key={d.id} className="detail-list-item">
              <span onClick={() => onNavigate('feature', d.id)} style={{ cursor: 'pointer' }}>
                F-{d.number} {d.title}
              </span>
            </div>
          ))}
        </div>
      )}
      {!adding && availableFeatures.length > 0 && (
        <button
          onClick={() => setAdding(true)}
          style={{
            marginTop: '8px', background: 'none', border: '1px solid var(--border)',
            color: 'var(--text-muted)', cursor: 'pointer', padding: '4px 10px',
            borderRadius: '4px', fontSize: '12px', fontFamily: 'var(--font-mono)',
          }}
        >+ Add dependency</button>
      )}
      {adding && (
        <div style={{ marginTop: '8px', display: 'flex', gap: '8px' }}>
          <select
            value={selectedId}
            onChange={e => setSelectedId(e.target.value)}
            style={{
              flex: 1, background: 'var(--bg-secondary)', border: '1px solid var(--border)',
              color: 'var(--text-primary)', padding: '4px 8px', borderRadius: '4px',
              fontSize: '12px', fontFamily: 'var(--font-mono)',
            }}
          >
            <option value="">Select feature...</option>
            {availableFeatures.map(f => (
              <option key={f.id} value={f.id}>F-{f.number} {f.title}</option>
            ))}
          </select>
          <button onClick={handleAdd} style={{
            background: 'var(--accent)', border: 'none', color: '#fff',
            cursor: 'pointer', padding: '4px 10px', borderRadius: '4px', fontSize: '12px',
          }}>Add</button>
          <button onClick={() => { setAdding(false); setSelectedId('') }} style={{
            background: 'none', border: '1px solid var(--border)', color: 'var(--text-muted)',
            cursor: 'pointer', padding: '4px 10px', borderRadius: '4px', fontSize: '12px',
          }}>Cancel</button>
        </div>
      )}
      {deps.length === 0 && dependents.length === 0 && !adding && (
        <div style={{ color: 'var(--text-muted)', fontSize: '12px', fontFamily: 'var(--font-mono)' }}>
          No dependencies
        </div>
      )}
    </div>
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
      {data.description && <div className="detail-description"><Markdown remarkPlugins={[remarkGfm]} components={mdComponents}>{data.description}</Markdown></div>}
      <DocumentChips docs={docs} />
      <FeatureDependencies data={data} onNavigate={onNavigate} />
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

function TaskDetail({ data, onNavigate, projectId, worktreeNames }: { data: TaskData; onNavigate: (type: 'epic' | 'feature' | 'task', id: string) => void; projectId?: string; worktreeNames?: Record<string, string> }) {
  const [notes, setNotes] = useState<TaskNote[]>([])
  useEffect(() => {
    api.getTaskNotes(data.id).then(setNotes).catch(() => {})
  }, [data.id])

  useEffect(() => {
    if (!projectId) return
    api.dismissTaskNotification(projectId, data.id).then(() => {
      const refresh = (window as any).__notificationBellRefresh
      if (typeof refresh === 'function') refresh()
    }).catch(() => {})
  }, [projectId, data.id])

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
          {data.worktree_id && <span className="detail-agent">{worktreeNames?.[data.worktree_id] ?? 'agent (removed)'}</span>}
        </div>
      </div>
      {data.description && <div className="detail-description"><Markdown remarkPlugins={[remarkGfm]} components={mdComponents}>{data.description}</Markdown></div>}
      {notes.length > 0 && (
        <div className="detail-section">
          <h3>Notes</h3>
          <div className="detail-notes">
            {notes.map(n => (
              <div key={n.id} className="detail-note">
                <div className="detail-note-time">{new Date(n.created_at).toLocaleString()}</div>
                <div className="detail-description"><Markdown remarkPlugins={[remarkGfm]} components={mdComponents}>{n.note.replace(/\\n/g, '\n')}</Markdown></div>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  )
}
