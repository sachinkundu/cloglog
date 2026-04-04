import { useCallback, useState } from 'react'
import { Board } from './components/Board'
import { DetailPanel } from './components/DetailPanel'
import { Layout } from './components/Layout'
import { useBoard } from './hooks/useBoard'
import { useProjects } from './hooks/useProjects'
import type { BacklogEpic } from './api/types'

type DetailState =
  | { type: 'epic'; data: any }
  | { type: 'feature'; data: any }
  | { type: 'task'; data: any }
  | null

export default function App() {
  const { projects, loading: projectsLoading } = useProjects()
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null)
  const { board, backlog, worktrees, loading: boardLoading } = useBoard(selectedProjectId)
  const [detail, setDetail] = useState<DetailState>(null)

  const openDetail = useCallback((type: 'epic' | 'feature' | 'task', id: string) => {
    if (type === 'epic') {
      const entry = backlog.find(e => e.epic.id === id)
      if (entry) {
        setDetail({
          type: 'epic',
          data: {
            title: entry.epic.title,
            description: entry.epic.description,
            color: entry.epic.color,
            bounded_context: entry.epic.bounded_context,
            task_counts: entry.task_counts,
            features: entry.features.map(f => ({
              title: f.feature.title,
              task_counts: f.task_counts,
            })),
          },
        })
      }
    } else if (type === 'feature') {
      for (const entry of backlog) {
        const feat = entry.features.find(f => f.feature.id === id)
        if (feat) {
          setDetail({
            type: 'feature',
            data: {
              title: feat.feature.title,
              description: feat.feature.description,
              epic: { title: entry.epic.title, id: entry.epic.id, color: entry.epic.color },
              task_counts: feat.task_counts,
              tasks: feat.tasks.map(t => ({ id: t.id, title: t.title, status: t.status })),
            },
          })
          break
        }
      }
    } else {
      // Task — search in board columns first, then backlog
      if (board) {
        for (const col of board.columns) {
          const task = col.tasks.find(t => t.id === id)
          if (task) {
            const epicInfo = findEpicForTask(backlog, id, task.epic_title, task.epic_color)
            const featureInfo = findFeatureForTask(backlog, id, task.feature_title)
            setDetail({
              type: 'task',
              data: {
                title: task.title,
                description: task.description,
                status: task.status,
                priority: task.priority,
                epic: epicInfo,
                feature: featureInfo,
                worktree_id: task.worktree_id,
              },
            })
            return
          }
        }
      }
      // Search backlog
      for (const entry of backlog) {
        for (const feat of entry.features) {
          const t = feat.tasks.find(bt => bt.id === id)
          if (t) {
            setDetail({
              type: 'task',
              data: {
                title: t.title,
                description: '',
                status: t.status,
                priority: t.priority,
                epic: { title: entry.epic.title, id: entry.epic.id, color: entry.epic.color },
                feature: { title: feat.feature.title, id: feat.feature.id },
                worktree_id: null,
              },
            })
            return
          }
        }
      }
    }
  }, [backlog, board])

  const handleTaskClick = useCallback((taskId: string) => {
    openDetail('task', taskId)
  }, [openDetail])

  return (
    <Layout
      projects={projects}
      selectedProjectId={selectedProjectId}
      onSelectProject={setSelectedProjectId}
      worktrees={worktrees}
    >
      {!selectedProjectId && (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          flex: 1, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '14px',
        }}>
          {projectsLoading ? 'loading projects...' : 'select a project'}
        </div>
      )}

      {selectedProjectId && boardLoading && (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          flex: 1, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '14px',
        }}>
          loading board...
        </div>
      )}

      {board && !boardLoading && (
        <Board
          board={board}
          backlog={backlog}
          onTaskClick={handleTaskClick}
          onItemClick={openDetail}
        />
      )}

      {detail && (
        <DetailPanel
          type={detail.type}
          data={detail.data}
          onClose={() => setDetail(null)}
          onNavigate={openDetail}
        />
      )}
    </Layout>
  )
}

function findEpicForTask(backlog: BacklogEpic[], taskId: string, fallbackTitle: string, fallbackColor: string) {
  for (const e of backlog) {
    for (const f of e.features) {
      if (f.tasks.some(t => t.id === taskId)) {
        return { title: e.epic.title, id: e.epic.id, color: e.epic.color }
      }
    }
  }
  return { title: fallbackTitle, id: '', color: fallbackColor }
}

function findFeatureForTask(backlog: BacklogEpic[], taskId: string, fallbackTitle: string) {
  for (const e of backlog) {
    for (const f of e.features) {
      if (f.tasks.some(t => t.id === taskId)) {
        return { title: f.feature.title, id: f.feature.id }
      }
    }
  }
  return { title: fallbackTitle, id: '' }
}
