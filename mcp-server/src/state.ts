/**
 * Per-worktree state file written at register_agent and cleared at
 * unregister_agent. Lives at ``<worktree_path>/.cloglog/state.json``.
 *
 * The file exists so out-of-process tooling — most importantly the
 * PreToolUse hook ``plugins/cloglog/hooks/require-task-for-pr.sh`` — can
 * resolve ``worktree_id`` and ``agent_token`` for the current shell's
 * working directory without needing a live MCP session. Without this
 * file the hook can only print an advisory reminder; with it, the hook
 * can call ``GET /api/v1/agents/{worktree_id}/tasks`` and hard-block
 * ``gh pr create`` when no task is in_progress (T-371).
 */

import { mkdir, writeFile, unlink } from 'node:fs/promises'
import { join } from 'node:path'

export interface WorktreeState {
  worktree_id: string
  project_id: string
  agent_token: string
  backend_url: string
  ts: string
}

export async function writeWorktreeState(
  worktreePath: string,
  state: WorktreeState,
): Promise<void> {
  const dir = join(worktreePath, '.cloglog')
  await mkdir(dir, { recursive: true })
  const path = join(dir, 'state.json')
  // 0o600 — token is sensitive; readable by the agent uid only.
  await writeFile(path, JSON.stringify(state, null, 2) + '\n', { mode: 0o600 })
}

export async function clearWorktreeState(worktreePath: string): Promise<void> {
  const path = join(worktreePath, '.cloglog', 'state.json')
  try {
    await unlink(path)
  } catch (err: unknown) {
    if ((err as NodeJS.ErrnoException)?.code !== 'ENOENT') {
      throw err
    }
  }
}
