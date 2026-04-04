import type { ReactNode } from 'react'
import type { Project, Worktree } from '../api/types'
import { Sidebar } from './Sidebar'
import { ThemeToggle } from './ThemeToggle'
import './Layout.css'

interface LayoutProps {
  projects: Project[]
  selectedProjectId: string | null
  worktrees: Worktree[]
  children: ReactNode
}

export function Layout({ projects, selectedProjectId, worktrees, children }: LayoutProps) {
  return (
    <div className="layout">
      <Sidebar
        projects={projects}
        selectedProjectId={selectedProjectId}
        worktrees={worktrees}
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
