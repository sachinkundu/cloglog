import type { Project, Worktree } from '../api/types'
import './Sidebar.css'

interface SidebarProps {
  projects: Project[]
  selectedProjectId: string | null
  onSelectProject: (id: string) => void
  worktrees: Worktree[]
}

export function Sidebar({ projects, selectedProjectId, onSelectProject, worktrees }: SidebarProps) {
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
                onClick={() => onSelectProject(p.id)}
              >
                <span className={`status-dot ${p.status}`} />
                <span className="project-name">{p.name}</span>
              </button>
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
