import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { NotificationBell } from './NotificationBell'
import type { AppNotification } from '../api/types'

vi.mock('../api/client', () => ({
  api: {
    getNotifications: vi.fn(),
    markNotificationRead: vi.fn(),
    markAllNotificationsRead: vi.fn(),
    dismissTaskNotification: vi.fn(),
    streamUrl: vi.fn().mockReturnValue('http://test/stream'),
  },
}))

vi.mock('../hooks/useSSE', () => ({
  useSSE: vi.fn(),
}))

import { api } from '../api/client'
const mockApi = vi.mocked(api)

const makeNotification = (overrides: Partial<AppNotification> = {}): AppNotification => ({
  id: 'n1',
  project_id: 'p1',
  task_id: 't1',
  task_title: 'Build login page',
  task_number: 42,
  read: false,
  created_at: new Date(Date.now() - 2 * 60 * 1000).toISOString(), // 2 minutes ago
  ...overrides,
})

beforeEach(() => {
  vi.clearAllMocks()
  mockApi.markNotificationRead.mockResolvedValue(makeNotification({ read: true }))
  mockApi.markAllNotificationsRead.mockResolvedValue({ marked_read: 0 })
})

describe('NotificationBell', () => {
  it('shows badge with unread count', async () => {
    const notifs = [
      makeNotification({ id: 'n1', task_id: 't1', read: false }),
      makeNotification({ id: 'n2', task_id: 't2', read: false }),
    ]
    mockApi.getNotifications.mockResolvedValue(notifs)

    render(
      <NotificationBell projectId="p1" onNavigate={vi.fn()} />
    )

    await waitFor(() => {
      expect(screen.getByTestId('notif-badge')).toBeInTheDocument()
    })
    expect(screen.getByTestId('notif-badge').textContent).toBe('2')
  })

  it('hides badge when no unread notifications', async () => {
    mockApi.getNotifications.mockResolvedValue([])

    render(
      <NotificationBell projectId="p1" onNavigate={vi.fn()} />
    )

    // Give time for any async effects
    await waitFor(() => {
      expect(mockApi.getNotifications).toHaveBeenCalled()
    })

    expect(screen.queryByTestId('notif-badge')).not.toBeInTheDocument()
  })

  it('clicking notification calls onNavigate', async () => {
    const user = userEvent.setup()
    const onNavigate = vi.fn()
    const notif = makeNotification({ id: 'n1', task_id: 't1', task_number: 42, task_title: 'Build login page' })
    mockApi.getNotifications.mockResolvedValue([notif])

    render(
      <NotificationBell projectId="p1" onNavigate={onNavigate} />
    )

    // Open the dropdown
    await user.click(screen.getByTestId('notif-bell'))

    // Click the notification item
    const item = await screen.findByText('T-42: Build login page')
    await user.click(item)

    expect(mockApi.markNotificationRead).toHaveBeenCalledWith('n1')
    expect(onNavigate).toHaveBeenCalledWith('task', 't1')
  })

  it('clear all marks all read', async () => {
    const user = userEvent.setup()
    const notifs = [
      makeNotification({ id: 'n1', task_id: 't1', read: false }),
    ]
    mockApi.getNotifications.mockResolvedValue(notifs)
    mockApi.markAllNotificationsRead.mockResolvedValue({ marked_read: 1 })

    render(
      <NotificationBell projectId="p1" onNavigate={vi.fn()} />
    )

    // Open the dropdown
    await user.click(screen.getByTestId('notif-bell'))

    // Click "Clear all"
    const clearBtn = await screen.findByText('Clear all')
    await user.click(clearBtn)

    expect(mockApi.markAllNotificationsRead).toHaveBeenCalledWith('p1')
  })
})
