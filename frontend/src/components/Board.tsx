import type { BoardResponse } from '../api/types'
import { BoardHeader } from './BoardHeader'
import { Column } from './Column'
import './Board.css'

interface BoardProps {
  board: BoardResponse
  onTaskClick: (taskId: string) => void
}

export function Board({ board, onTaskClick }: BoardProps) {
  return (
    <div className="board">
      <BoardHeader board={board} />
      <div className="board-columns">
        {board.columns.map(col => (
          <Column key={col.status} column={col} onTaskClick={onTaskClick} />
        ))}
      </div>
    </div>
  )
}
