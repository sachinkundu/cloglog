import { useCallback, useState } from 'react'
import type { TaskCard as TaskCardType } from './api/types'
import { Board } from './components/Board'
import { CardDetail } from './components/CardDetail'
import { Layout } from './components/Layout'
import { useBoard } from './hooks/useBoard'
import { useProjects } from './hooks/useProjects'

export default function App() {
  const { projects, loading: projectsLoading } = useProjects()
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null)
  const { board, worktrees, loading: boardLoading } = useBoard(selectedProjectId)
  const [selectedTask, setSelectedTask] = useState<TaskCardType | null>(null)

  const handleTaskClick = useCallback((taskId: string) => {
    if (!board) return
    for (const col of board.columns) {
      const task = col.tasks.find(t => t.id === taskId)
      if (task) {
        setSelectedTask(task)
        return
      }
    }
  }, [board])

  return (
    <Layout
      projects={projects}
      selectedProjectId={selectedProjectId}
      onSelectProject={setSelectedProjectId}
      worktrees={worktrees}
    >
      {!selectedProjectId && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flex: 1,
          color: 'var(--text-muted)',
          fontFamily: 'var(--font-mono)',
          fontSize: '14px',
        }}>
          {projectsLoading ? 'loading projects...' : 'select a project'}
        </div>
      )}

      {selectedProjectId && boardLoading && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flex: 1,
          color: 'var(--text-muted)',
          fontFamily: 'var(--font-mono)',
          fontSize: '14px',
        }}>
          loading board...
        </div>
      )}

      {board && !boardLoading && (
        <Board board={board} onTaskClick={handleTaskClick} />
      )}

      {selectedTask && (
        <CardDetail task={selectedTask} onClose={() => setSelectedTask(null)} />
      )}
    </Layout>
  )
}
