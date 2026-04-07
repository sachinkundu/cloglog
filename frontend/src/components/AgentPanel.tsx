import { useState } from 'react'
import type { Worktree } from '../api/types'
import { api } from '../api/client'
import './AgentPanel.css'

interface AgentPanelProps {
  worktrees: Worktree[]
  projectId: string
  agentTaskCounts?: Record<string, number>
  onRefresh?: () => void
}

function formatHeartbeat(ts: string | null): string {
  if (!ts) return 'never'
  const diff = Date.now() - new Date(ts).getTime()
  const secs = Math.floor(diff / 1000)
  if (secs < 60) return `${secs}s ago`
  const mins = Math.floor(secs / 60)
  if (mins < 60) return `${mins}m ago`
  return `${Math.floor(mins / 60)}h ago`
}

export function AgentPanel({ worktrees, projectId, agentTaskCounts, onRefresh }: AgentPanelProps) {
  const [expanded, setExpanded] = useState<string | null>(null)
  const [shutdownPending, setShutdownPending] = useState<Set<string>>(new Set())

  const handleShutdown = async (worktreeId: string) => {
    setShutdownPending(prev => new Set(prev).add(worktreeId))
    try {
      await api.requestWorktreeShutdown(projectId, worktreeId)
      onRefresh?.()
    } catch {
      setShutdownPending(prev => {
        const next = new Set(prev)
        next.delete(worktreeId)
        return next
      })
    }
  }

  if (worktrees.length === 0) return null

  return (
    <section className="agent-panel">
      <h2 className="sidebar-section-title">Manage Agents</h2>
      <div className="agent-panel-list">
        {worktrees.map(wt => {
          const isExpanded = expanded === wt.id
          const taskCount = agentTaskCounts?.[wt.id] ?? 0
          const isPending = shutdownPending.has(wt.id)
          return (
            <div key={wt.id} className="agent-panel-item">
              <div
                className="agent-panel-header"
                onClick={() => setExpanded(isExpanded ? null : wt.id)}
                role="button"
              >
                <span className={`status-dot ${wt.status} ${wt.status === 'online' ? 'pulse' : ''}`} />
                <span className="agent-panel-name">{wt.name}</span>
                <span className="agent-panel-toggle">{isExpanded ? '\u25BC' : '\u25B6'}</span>
              </div>
              {isExpanded && (
                <div className="agent-panel-details">
                  <div className="agent-panel-row">
                    <span className="agent-panel-label">Status</span>
                    <span className={`agent-panel-value status-${wt.status}`}>{wt.status}</span>
                  </div>
                  <div className="agent-panel-row">
                    <span className="agent-panel-label">Branch</span>
                    <span className="agent-panel-value">{wt.branch_name || '\u2014'}</span>
                  </div>
                  <div className="agent-panel-row">
                    <span className="agent-panel-label">Heartbeat</span>
                    <span className="agent-panel-value">{formatHeartbeat(wt.last_heartbeat)}</span>
                  </div>
                  <div className="agent-panel-row">
                    <span className="agent-panel-label">Tasks</span>
                    <span className="agent-panel-value">{taskCount}</span>
                  </div>
                  {wt.status === 'online' && (
                    <button
                      className="agent-panel-shutdown"
                      onClick={(e) => { e.stopPropagation(); handleShutdown(wt.id) }}
                      disabled={isPending}
                    >
                      {isPending ? 'Requesting...' : 'Request Shutdown'}
                    </button>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}
