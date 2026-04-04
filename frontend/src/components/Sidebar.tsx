import { useNavigate } from 'react-router-dom'
import type { Project, Worktree } from '../api/types'
import './Sidebar.css'

interface BoardStats {
  total_tasks: number
  done_count: number
}

interface SidebarProps {
  projects: Project[]
  selectedProjectId: string | null
  worktrees: Worktree[]
  boardStats?: BoardStats | null
}

export function Sidebar({ projects, selectedProjectId, worktrees, boardStats }: SidebarProps) {
  const navigate = useNavigate()

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <h1 className="sidebar-title">cloglog</h1>
      </div>

      <section className="sidebar-section">
        <h2 className="sidebar-section-title">Projects</h2>
        <ul className="project-list">
          {projects.map(p => (
            <li key={p.id}>
              <button
                className={`project-item ${p.id === selectedProjectId ? 'selected' : ''}`}
                onClick={() => navigate(`/projects/${p.id}`)}
              >
                <span className={`status-dot ${p.status}`} />
                <span className="project-name">{p.name}</span>
              </button>
              {p.id === selectedProjectId && boardStats && (
                <div className="project-stats">
                  {worktrees.length} agent{worktrees.length !== 1 ? 's' : ''} · {boardStats.done_count}/{boardStats.total_tasks} done
                </div>
              )}
            </li>
          ))}
        </ul>
      </section>

      {selectedProjectId && worktrees.length > 0 && (
        <section className="sidebar-section">
          <h2 className="sidebar-section-title">Agents</h2>
          <ul className="worktree-list">
            {worktrees.map(wt => (
              <li key={wt.id} className="worktree-item">
                <span className={`status-dot ${wt.status} ${wt.status === 'online' ? 'pulse' : ''}`} />
                <span className="worktree-name">{wt.name}</span>
                <span className="worktree-status">{wt.status}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </aside>
  )
}
