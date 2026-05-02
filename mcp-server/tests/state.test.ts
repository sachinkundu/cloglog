import { describe, it, expect } from 'vitest'
import { mkdtemp, readFile, stat, access, mkdir, writeFile, chmod } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { writeWorktreeState, clearWorktreeState } from '../src/state.js'

describe('writeWorktreeState', () => {
  it('creates .cloglog/state.json with all required fields', async () => {
    const wt = await mkdtemp(join(tmpdir(), 'cloglog-state-'))
    await writeWorktreeState(wt, {
      worktree_id: 'wt-1',
      project_id: 'proj-1',
      agent_token: 'tok-1',
      backend_url: 'http://127.0.0.1:8001',
      ts: '2026-05-02T00:00:00Z',
    })
    const body = JSON.parse(await readFile(join(wt, '.cloglog/state.json'), 'utf-8'))
    expect(body).toMatchObject({
      worktree_id: 'wt-1',
      project_id: 'proj-1',
      agent_token: 'tok-1',
      backend_url: 'http://127.0.0.1:8001',
    })
  })

  it('writes state.json with 0o600 permissions (token is sensitive)', async () => {
    const wt = await mkdtemp(join(tmpdir(), 'cloglog-state-'))
    await writeWorktreeState(wt, {
      worktree_id: 'wt-1',
      project_id: 'proj-1',
      agent_token: 'tok-1',
      backend_url: 'http://127.0.0.1:8001',
      ts: '2026-05-02T00:00:00Z',
    })
    const s = await stat(join(wt, '.cloglog/state.json'))
    // Mask off the file-type bits, keep just the permission bits.
    expect(s.mode & 0o777).toBe(0o600)
  })

  it('tightens permissions to 0o600 even when state.json already exists at a looser mode (codex review round 2)', async () => {
    const wt = await mkdtemp(join(tmpdir(), 'cloglog-state-'))
    // Pre-create state.json at 0o644 — simulates a manual copy or a
    // pre-T-371 build that wrote without the mode option. writeFile's
    // ``mode`` option only applies on creation, so naive code would
    // refresh the agent_token inside a still-world-readable file.
    await mkdir(join(wt, '.cloglog'), { recursive: true })
    const path = join(wt, '.cloglog/state.json')
    await writeFile(path, '{}', { mode: 0o644 })
    await chmod(path, 0o644)
    expect((await stat(path)).mode & 0o777).toBe(0o644)

    await writeWorktreeState(wt, {
      worktree_id: 'wt-1',
      project_id: 'proj-1',
      agent_token: 'tok-rotated',
      backend_url: 'http://127.0.0.1:8001',
      ts: '2026-05-02T00:00:00Z',
    })

    expect((await stat(path)).mode & 0o777).toBe(0o600)
  })

  it('creates the .cloglog directory when missing', async () => {
    const wt = await mkdtemp(join(tmpdir(), 'cloglog-state-'))
    // mkdtemp creates wt itself but not .cloglog/.
    await writeWorktreeState(wt, {
      worktree_id: 'wt-1',
      project_id: 'proj-1',
      agent_token: 'tok-1',
      backend_url: 'http://127.0.0.1:8001',
      ts: '2026-05-02T00:00:00Z',
    })
    await expect(access(join(wt, '.cloglog'))).resolves.toBeUndefined()
  })
})

describe('clearWorktreeState', () => {
  it('removes the file when present', async () => {
    const wt = await mkdtemp(join(tmpdir(), 'cloglog-state-'))
    await writeWorktreeState(wt, {
      worktree_id: 'wt-1',
      project_id: 'proj-1',
      agent_token: 'tok-1',
      backend_url: 'http://127.0.0.1:8001',
      ts: '2026-05-02T00:00:00Z',
    })
    await clearWorktreeState(wt)
    await expect(access(join(wt, '.cloglog/state.json'))).rejects.toBeTruthy()
  })

  it('is idempotent when the file does not exist (ENOENT swallowed)', async () => {
    const wt = await mkdtemp(join(tmpdir(), 'cloglog-state-'))
    await expect(clearWorktreeState(wt)).resolves.toBeUndefined()
  })
})
