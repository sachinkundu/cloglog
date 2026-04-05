import { useCallback, useMemo } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { Board } from './components/Board'
import { DependencyGraph } from './components/DependencyGraph'
import { DetailPanel } from './components/DetailPanel'
import { Layout } from './components/Layout'
import { useBoard } from './hooks/useBoard'
import { useDependencyGraph } from './hooks/useDependencyGraph'
import { useProjects } from './hooks/useProjects'
import type { BacklogEpic, BoardResponse, DependencyGraphResponse } from './api/types'

type DetailState =
  | { type: 'epic'; data: any }
  | { type: 'feature'; data: any }
  | { type: 'task'; data: any }
  | null

export default function App() {
  const { projectId, epicId, featureId, taskId } = useParams<{
    projectId?: string
    epicId?: string
    featureId?: string
    taskId?: string
  }>()
  const navigate = useNavigate()
  const location = useLocation()
  const isDependenciesView = location.pathname.endsWith('/dependencies')

  const selectedProjectId = projectId ?? null
  const { projects, loading: projectsLoading } = useProjects()
  const { board, backlog, worktrees, loading: boardLoading, refetch } = useBoard(selectedProjectId)
  const { graph: depGraph } = useDependencyGraph(selectedProjectId)

  const detail = useMemo<DetailState>(() => {
    if (!selectedProjectId) return null
    if (epicId) return buildEpicDetail(backlog, epicId)
    if (featureId) return buildFeatureDetail(backlog, featureId, depGraph)
    if (taskId) return buildTaskDetail(backlog, board, taskId)
    return null
  }, [selectedProjectId, epicId, featureId, taskId, backlog, board, depGraph])

  const openDetail = useCallback((type: 'epic' | 'feature' | 'task', id: string) => {
    if (!selectedProjectId) return
    const segment = type === 'epic' ? 'epics' : type === 'feature' ? 'features' : 'tasks'
    navigate(`/projects/${selectedProjectId}/${segment}/${id}`)
  }, [selectedProjectId, navigate])

  const closeDetail = useCallback(() => {
    if (selectedProjectId) {
      navigate(`/projects/${selectedProjectId}`)
    }
  }, [selectedProjectId, navigate])

  const handleTaskClick = useCallback((taskId: string) => {
    openDetail('task', taskId)
  }, [openDetail])

  return (
    <Layout
      projects={projects}
      selectedProjectId={selectedProjectId}
      worktrees={worktrees}
      boardStats={board ? { total_tasks: board.total_tasks, done_count: board.done_count } : null}
      onNavigate={openDetail}
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

      {board && !boardLoading && !isDependenciesView && (
        <Board
          board={board}
          backlog={backlog}
          projectId={selectedProjectId}
          onTaskClick={handleTaskClick}
          onItemClick={openDetail}
          onRefresh={refetch}
        />
      )}

      {selectedProjectId && isDependenciesView && (
        <DependencyGraph projectId={selectedProjectId} onItemClick={openDetail} />
      )}

      {detail && selectedProjectId && (
        <DetailPanel
          type={detail.type}
          data={detail.data}
          onClose={closeDetail}
          onNavigate={openDetail}
          projectId={selectedProjectId}
        />
      )}
    </Layout>
  )
}

function buildEpicDetail(backlog: BacklogEpic[], epicId: string): DetailState {
  const entry = backlog.find(e => e.epic.id === epicId)
  if (!entry) return null
  return {
    type: 'epic',
    data: {
      id: epicId,
      title: entry.epic.title,
      description: entry.epic.description,
      color: entry.epic.color,
      bounded_context: entry.epic.bounded_context,
      task_counts: entry.task_counts,
      number: entry.epic.number,
      features: entry.features.map(f => ({
        title: f.feature.title,
        task_counts: f.task_counts,
      })),
    },
  }
}

function buildFeatureDetail(backlog: BacklogEpic[], featureId: string, depGraph: DependencyGraphResponse | null): DetailState {
  for (const entry of backlog) {
    const feat = entry.features.find(f => f.feature.id === featureId)
    if (feat) {
      let dependencies: Array<{ id: string; title: string; number: number }> = []
      let dependents: Array<{ id: string; title: string; number: number }> = []
      let all_features: Array<{ id: string; title: string; number: number }> = []

      if (depGraph) {
        all_features = depGraph.nodes.map(n => ({ id: n.id, title: n.title, number: n.number }))
        dependencies = depGraph.edges
          .filter(e => e.to_id === featureId)
          .map(e => {
            const node = depGraph.nodes.find(n => n.id === e.from_id)
            return node ? { id: node.id, title: node.title, number: node.number } : null
          })
          .filter((x): x is { id: string; title: string; number: number } => x !== null)
        dependents = depGraph.edges
          .filter(e => e.from_id === featureId)
          .map(e => {
            const node = depGraph.nodes.find(n => n.id === e.to_id)
            return node ? { id: node.id, title: node.title, number: node.number } : null
          })
          .filter((x): x is { id: string; title: string; number: number } => x !== null)
      }

      return {
        type: 'feature',
        data: {
          id: featureId,
          title: feat.feature.title,
          description: feat.feature.description,
          epic: { title: entry.epic.title, id: entry.epic.id, color: entry.epic.color },
          task_counts: feat.task_counts,
          number: feat.feature.number,
          tasks: feat.tasks.map(t => ({ id: t.id, title: t.title, status: t.status })),
          dependencies,
          dependents,
          all_features,
        },
      }
    }
  }
  return null
}

function buildTaskDetail(backlog: BacklogEpic[], board: BoardResponse | null, taskId: string): DetailState {
  // Search board columns first
  if (board) {
    for (const col of board.columns) {
      const task = col.tasks.find(t => t.id === taskId)
      if (task) {
        const epicInfo = findEpicForTask(backlog, taskId, task.epic_title, task.epic_color)
        const featureInfo = findFeatureForTask(backlog, taskId, task.feature_title)
        return {
          type: 'task',
          data: {
            id: taskId,
            title: task.title,
            description: task.description,
            status: task.status,
            priority: task.priority,
            epic: epicInfo,
            feature: featureInfo,
            worktree_id: task.worktree_id,
            number: task.number,
          },
        }
      }
    }
  }
  // Search backlog
  for (const entry of backlog) {
    for (const feat of entry.features) {
      const t = feat.tasks.find(bt => bt.id === taskId)
      if (t) {
        return {
          type: 'task',
          data: {
            id: taskId,
            title: t.title,
            description: '',
            status: t.status,
            priority: t.priority,
            epic: { title: entry.epic.title, id: entry.epic.id, color: entry.epic.color },
            feature: { title: feat.feature.title, id: feat.feature.id },
            worktree_id: null,
            number: t.number,
          },
        }
      }
    }
  }
  return null
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
