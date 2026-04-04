import type { ReactNode } from 'react'
import type { Project, Worktree } from '../api/types'
import { Sidebar } from './Sidebar'
import { ThemeToggle } from './ThemeToggle'
import './Layout.css'

interface BoardStats {
  total_tasks: number
  done_count: number
}

interface LayoutProps {
  projects: Project[]
  selectedProjectId: string | null
  worktrees: Worktree[]
  boardStats?: BoardStats | null
  children: ReactNode
}

export function Layout({ projects, selectedProjectId, worktrees, boardStats, children }: LayoutProps) {
  return (
    <div className="layout">
      <Sidebar
        projects={projects}
        selectedProjectId={selectedProjectId}
        worktrees={worktrees}
        boardStats={boardStats}
      />
      <main className="main-content">
        <div className="main-header">
          <ThemeToggle />
        </div>
        {children}
      </main>
    </div>
  )
}
