import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Project, Worktree } from '../api/types'
import { AgentPanel } from './AgentPanel'
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
  agentFilter?: string | null
  onAgentClick?: (worktreeId: string) => void
  agentTaskCounts?: Record<string, number>
  onRefresh?: () => void
  onDeleteProject?: (projectId: string) => void
}

function getProjectHealth(worktrees: Worktree[], boardStats: BoardStats | null | undefined): 'green' | 'yellow' | 'red' {
  const hasOnlineAgents = worktrees.some(wt => wt.status === 'online')
  if (!hasOnlineAgents) return 'red'
  const hasTasksProgressing = worktrees.some(wt => wt.current_task_id !== null)
  return hasTasksProgressing ? 'green' : 'yellow'
}

export function Sidebar({ projects, selectedProjectId, worktrees, boardStats, agentFilter, onAgentClick, agentTaskCounts, onRefresh, onDeleteProject }: SidebarProps) {
  const navigate = useNavigate()
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('sidebar-collapsed') === 'true')
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; projectId: string } | null>(null)

  const handleContextMenu = useCallback((e: React.MouseEvent, projectId: string) => {
    e.preventDefault()
    setContextMenu({ x: e.clientX, y: e.clientY, projectId })
  }, [])

  const handleDelete = useCallback(() => {
    if (contextMenu) {
      onDeleteProject?.(contextMenu.projectId)
      setContextMenu(null)
    }
  }, [contextMenu, onDeleteProject])

  // Close context menu on click anywhere
  useEffect(() => {
    if (!contextMenu) return
    const close = () => setContextMenu(null)
    document.addEventListener('click', close)
    return () => document.removeEventListener('click', close)
  }, [contextMenu])

  const toggleCollapsed = () => {
    setCollapsed(prev => {
      const next = !prev
      localStorage.setItem('sidebar-collapsed', String(next))
      return next
    })
  }

  return (
    <aside className={`sidebar ${collapsed ? 'sidebar-collapsed' : ''}`}>
      <div className="sidebar-header">
        {!collapsed && <h1 className="sidebar-title">cloglog</h1>}
        <button className="sidebar-toggle" onClick={toggleCollapsed} title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}>
          {collapsed ? '\u25B6' : '\u25C0'}
        </button>
      </div>

      {!collapsed && (
        <>
          <section className="sidebar-section">
            <h2 className="sidebar-section-title">Projects</h2>
            <ul className="project-list">
              {projects.map(p => (
                <li key={p.id}>
                  <button
                    className={`project-item ${p.id === selectedProjectId ? 'selected' : ''}`}
                    onClick={() => navigate(`/projects/${p.id}`)}
                    onContextMenu={(e) => handleContextMenu(e, p.id)}
                  >
                    {p.id === selectedProjectId && boardStats ? (
                      <span className={`status-dot project-health health-${getProjectHealth(worktrees, boardStats)}`} />
                    ) : (
                      <span className={`status-dot ${p.status}`} />
                    )}
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
                {worktrees.map(wt => {
                  const taskCount = agentTaskCounts?.[wt.id] ?? 0
                  return (
                    <li
                      key={wt.id}
                      className={`worktree-item ${agentFilter === wt.id ? 'worktree-active' : ''}`}
                      onClick={() => onAgentClick?.(wt.id)}
                      title={`${taskCount} task${taskCount !== 1 ? 's' : ''}`}
                      role="button"
                    >
                      <span className={`status-dot ${wt.status} ${wt.status === 'online' ? 'pulse' : ''}`} />
                      <span className="worktree-name">{wt.name}</span>
                      <span className="worktree-task-count">{taskCount}</span>
                      <span className="worktree-status">{wt.status}</span>
                    </li>
                  )
                })}
              </ul>
            </section>
          )}

          {selectedProjectId && worktrees.length > 0 && (
            <AgentPanel
              worktrees={worktrees}
              projectId={selectedProjectId}
              agentTaskCounts={agentTaskCounts}
              onRefresh={onRefresh}
            />
          )}
        </>
      )}

      {contextMenu && (
        <div
          className="context-menu"
          style={{ top: contextMenu.y, left: contextMenu.x }}
          data-testid="context-menu"
        >
          <button className="context-menu-item danger" onClick={handleDelete}>
            Delete project
          </button>
        </div>
      )}
    </aside>
  )
}
