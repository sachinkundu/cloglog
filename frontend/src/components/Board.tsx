import type { BacklogEpic, BoardResponse } from '../api/types'
import { BacklogTree } from './BacklogTree'
import { BoardHeader } from './BoardHeader'
import { Column } from './Column'
import './Board.css'

interface BoardProps {
  board: BoardResponse
  backlog: BacklogEpic[]
  projectId: string
  onTaskClick: (taskId: string) => void
  onItemClick: (type: 'epic' | 'feature' | 'task', id: string) => void
  onRefresh?: () => void
}

export function Board({ board, backlog, projectId, onTaskClick, onItemClick, onRefresh }: BoardProps) {
  const flowColumns = board.columns.filter(col => col.status !== 'backlog')

  return (
    <div className="board">
      <BoardHeader board={board} projectId={projectId} onItemClick={onItemClick} />
      <div className="board-columns">
        <div className="board-backlog">
          <div className="column-header">
            <span className="column-dot col-backlog" />
            <span className="column-title">Backlog</span>
            <span className="column-count">
              {board.columns.find(c => c.status === 'backlog')?.tasks.length ?? 0}
            </span>
          </div>
          <BacklogTree backlog={backlog} onItemClick={onItemClick} />
        </div>
        {flowColumns.map(col => (
          <Column key={col.status} column={col} onTaskClick={onTaskClick} onRefresh={onRefresh} />
        ))}
      </div>
    </div>
  )
}
