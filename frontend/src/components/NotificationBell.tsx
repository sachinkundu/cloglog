import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { AppNotification } from '../api/types'
import { useSSE } from '../hooks/useSSE'
import './NotificationBell.css'

interface NotificationBellProps {
  projectId: string | null
  onNavigate: (type: 'epic' | 'feature' | 'task', id: string) => void
}

function formatRelativeTime(isoString: string): string {
  const now = Date.now()
  const then = new Date(isoString).getTime()
  const diffMs = now - then
  const diffSec = Math.floor(diffMs / 1000)
  if (diffSec < 60) return `${diffSec}s ago`
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  const diffDay = Math.floor(diffHr / 24)
  return `${diffDay}d ago`
}

export function NotificationBell({ projectId, onNavigate }: NotificationBellProps) {
  const [notifications, setNotifications] = useState<AppNotification[]>([])
  const [open, setOpen] = useState(false)
  const wrapperRef = useRef<HTMLDivElement>(null)

  const fetchNotifications = useCallback(() => {
    if (!projectId) return
    api.getNotifications(projectId).then(setNotifications).catch(() => {})
  }, [projectId])

  useEffect(() => {
    fetchNotifications()
  }, [fetchNotifications])

  // Expose for auto-dismiss integration
  useEffect(() => {
    ;(window as any).__notificationBellRefresh = fetchNotifications
    return () => {
      delete (window as any).__notificationBellRefresh
    }
  }, [fetchNotifications])

  // Subscribe to SSE notification_created events
  useSSE(projectId, (event) => {
    if (event.type === 'notification_created') {
      fetchNotifications()
    }
  })

  // Close dropdown on outside click
  useEffect(() => {
    if (!open) return
    function handleMouseDown(e: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleMouseDown)
    return () => document.removeEventListener('mousedown', handleMouseDown)
  }, [open])

  const unreadCount = notifications.filter(n => !n.read).length

  function handleBellClick() {
    setOpen(prev => !prev)
  }

  async function handleItemClick(notification: AppNotification) {
    try {
      await api.markNotificationRead(notification.id)
    } catch {
      // continue even if marking read fails
    }
    setNotifications(prev => prev.filter(n => n.id !== notification.id))
    setOpen(false)
    onNavigate('task', notification.task_id)
  }

  async function handleClearAll() {
    if (!projectId) return
    try {
      await api.markAllNotificationsRead(projectId)
    } catch {
      // continue even if the request fails
    }
    setNotifications([])
    setOpen(false)
  }

  return (
    <div className="notif-wrapper" ref={wrapperRef}>
      <button
        className="notif-bell"
        data-testid="notif-bell"
        onClick={handleBellClick}
        aria-label="Notifications"
      >
        🔔
        {unreadCount > 0 && (
          <span className="notif-badge" data-testid="notif-badge">
            {unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="notif-dropdown" data-testid="notif-dropdown">
          {notifications.length === 0 ? (
            <div className="notif-empty">No notifications</div>
          ) : (
            <>
              <ul className="notif-list">
                {notifications.map(n => (
                  <li
                    key={n.id}
                    className={`notif-item${n.read ? ' notif-item--read' : ''}`}
                    onClick={() => handleItemClick(n)}
                  >
                    <span className="notif-item-title">
                      T-{n.task_number}: {n.task_title}
                    </span>
                    <span className="notif-item-time">{formatRelativeTime(n.created_at)}</span>
                  </li>
                ))}
              </ul>
              <div className="notif-footer">
                <button className="notif-clear-all" onClick={handleClearAll}>
                  Clear all
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
