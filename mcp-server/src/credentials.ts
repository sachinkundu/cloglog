/**
 * Credential resolution for the cloglog MCP server.
 *
 * The project API key (`CLOGLOG_API_KEY`) MUST live outside of any per-worktree
 * file so that processes inside a worktree cannot read it from disk and bypass
 * the "agents talk to the backend only via MCP" rule.
 *
 * Resolution order (T-382 — per-project credentials so multi-project hosts
 * don't send the wrong project's key and earn silent 401s):
 *   1. `process.env.CLOGLOG_API_KEY` (explicit override).
 *   2. `~/.cloglog/credentials.d/<project_slug>` — per-project key file.
 *      The slug comes from `<project_root>/.cloglog/config.yaml: project`,
 *      falling back to `basename(project_root)`. The project root is found
 *      by walking up from `process.cwd()` until a `.cloglog/config.yaml`
 *      appears.
 *   3. `~/.cloglog/credentials` — legacy single-project fallback. Hosts
 *      with one project keep working unchanged.
 *
 * If none of these yield a non-empty key, `loadApiKey` throws
 * `MissingCredentialsError` naming every path it tried.
 */

import { existsSync, readFileSync, statSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join } from 'node:path'

export const CREDENTIALS_DIR = join(homedir(), '.cloglog')
export const DEFAULT_CREDENTIALS_PATH = join(CREDENTIALS_DIR, 'credentials')
export const DEFAULT_PROJECT_CREDENTIALS_DIR = join(CREDENTIALS_DIR, 'credentials.d')

/**
 * Slug must be filesystem-safe and free of path-traversal characters; matches
 * the bash `_project_slug` validator in `plugins/cloglog/skills/launch/SKILL.md`.
 * Anything else is rejected — fail loud, do not silently fall back.
 */
const SLUG_RE = /^[A-Za-z0-9._-]+$/

export class MissingCredentialsError extends Error {
  constructor(
    public readonly credentialsPath: string,
    public readonly projectCredentialsPath: string | null,
    public readonly projectSlug: string | null,
  ) {
    const triedLines: string[] = ['  - $CLOGLOG_API_KEY (env)']
    if (projectCredentialsPath) {
      triedLines.push(`  - ${projectCredentialsPath} (per-project, slug=${projectSlug})`)
    }
    triedLines.push(`  - ${credentialsPath} (legacy global)`)

    super(
      [
        'cloglog-mcp: CLOGLOG_API_KEY is not set and no usable credentials file was found.',
        '',
        'Looked in:',
        ...triedLines,
        '',
        'Fix this by either:',
        '  1) Exporting CLOGLOG_API_KEY in the shell that launches the MCP server, OR',
        projectCredentialsPath
          ? `  2) Creating ${projectCredentialsPath} with this project's key:`
          : `  2) Creating ${credentialsPath} with the project key:`,
        '       mkdir -p ~/.cloglog' + (projectCredentialsPath ? '/credentials.d' : ''),
        `       printf "CLOGLOG_API_KEY=<your-project-key>\\n" > ${projectCredentialsPath ?? credentialsPath}`,
        `       chmod 600 ${projectCredentialsPath ?? credentialsPath}`,
        '',
        'See docs/setup-credentials.md.',
      ].join('\n'),
    )
    this.name = 'MissingCredentialsError'
  }
}

/**
 * The per-project credentials file at `~/.cloglog/credentials.d/<slug>`
 * exists, but cannot yield a usable `CLOGLOG_API_KEY` (unreadable, points
 * at a directory, or contains an empty/missing key). Refuse to fall back
 * to the legacy global file — the global file may belong to a different
 * project, and silently sending its key recreates the silent-401 bug
 * T-382 was filed to remove. Fail loud.
 */
export class UnusableProjectCredentialsError extends Error {
  constructor(
    public readonly projectCredentialsPath: string,
    public readonly projectSlug: string,
    public readonly reason: 'unreadable' | 'is_directory' | 'empty_or_no_key',
  ) {
    super(
      [
        `cloglog-mcp: per-project credentials file ${projectCredentialsPath} exists but is unusable (${reason}).`,
        '',
        `Refusing to fall back to ~/.cloglog/credentials — that file may hold a different project's key, and`,
        `sending it would silently mis-auth every agent call from this project (the original T-382 bug).`,
        '',
        'Fix this by one of:',
        `  1) chmod 600 ${projectCredentialsPath} (if perms wrong)`,
        `  2) printf "CLOGLOG_API_KEY=<this project's key>\\n" > ${projectCredentialsPath} (if blank)`,
        `  3) rm ${projectCredentialsPath} (if you intend to use the legacy global file for this project)`,
        '',
        `Slug derived from .cloglog/config.yaml: project: ${projectSlug}`,
        'See docs/setup-credentials.md.',
      ].join('\n'),
    )
    this.name = 'UnusableProjectCredentialsError'
  }
}

/**
 * `.cloglog/config.yaml` has `project_id` set, which means this checkout
 * has a specific project identity — but no per-project credentials file
 * exists for it. Falling through to the legacy global file would silently
 * authenticate as whatever project owns `~/.cloglog/credentials`, recreating
 * the T-398 incident where an antisocial session bound to cloglog because
 * `~/.cloglog/credentials.d/antisocial` was absent. Fail loud.
 */
export class ProjectIdSetMissingCredentialsError extends Error {
  constructor(
    public readonly projectId: string,
    public readonly projectSlug: string,
    public readonly expectedCredentialsPath: string,
  ) {
    super(
      [
        `cloglog-mcp: .cloglog/config.yaml sets project_id=${projectId} but no per-project credentials file was found.`,
        '',
        `Expected: ${expectedCredentialsPath} (per-project, slug=${projectSlug})`,
        '',
        `When project_id is set, the legacy ~/.cloglog/credentials fallback is disabled`,
        `to prevent silently authenticating as the wrong project (T-398 hardening).`,
        '',
        `Fix: run /cloglog init to mint and write the per-project key, OR manually:`,
        `  mkdir -p ~/.cloglog/credentials.d`,
        `  printf "CLOGLOG_API_KEY=<this project's key>\\n" > ${expectedCredentialsPath}`,
        `  chmod 600 ${expectedCredentialsPath}`,
        '',
        'See docs/setup-credentials.md.',
      ].join('\n'),
    )
    this.name = 'ProjectIdSetMissingCredentialsError'
  }
}

export interface LoadApiKeyOptions {
  /** Legacy global credentials path. Defaults to `~/.cloglog/credentials`. */
  credentialsPath?: string
  /** Per-project credentials directory. Defaults to `~/.cloglog/credentials.d`. */
  projectCredentialsDir?: string
  /** Where to start the walk-up looking for `.cloglog/config.yaml`. Defaults to `process.cwd()`. */
  projectRoot?: string
  /** Process env. Defaults to `process.env`. */
  env?: NodeJS.ProcessEnv
}

/**
 * Walk up from `start` until a directory contains `.cloglog/config.yaml`.
 * Returns null if no such ancestor exists (e.g. invoked from outside any
 * cloglog-managed project).
 */
export function findProjectRoot(start: string): string | null {
  let cur = start
  // Cap the walk at filesystem root; `dirname('/') === '/'` is the terminator.
  for (let i = 0; i < 64; i++) {
    if (existsSync(join(cur, '.cloglog', 'config.yaml'))) return cur
    const parent = dirname(cur)
    if (parent === cur) return null
    cur = parent
  }
  return null
}

/**
 * Resolve the project slug for per-project credential lookup.
 * Reads `<projectRoot>/.cloglog/config.yaml: project` first; falls back to
 * `basename(projectRoot)`. Validates against `SLUG_RE`; returns null if
 * neither source produces a slug-safe identifier.
 */
export function resolveProjectSlug(projectRoot: string): string | null {
  const cfgPath = join(projectRoot, '.cloglog', 'config.yaml')
  let yamlSlug: string | null = null
  try {
    const content = readFileSync(cfgPath, 'utf8')
    // T-312 precedent: stdlib-only scalar parse, do NOT pull in a YAML lib.
    const m = content.match(/^project:[ \t]*(.+?)[ \t]*(?:#.*)?$/m)
    if (m) {
      let raw = m[1].trim()
      if (
        raw.length >= 2 &&
        ((raw.startsWith('"') && raw.endsWith('"')) ||
          (raw.startsWith("'") && raw.endsWith("'")))
      ) {
        raw = raw.substring(1, raw.length - 1)
      }
      yamlSlug = raw
    }
  } catch {
    // Missing config.yaml is fine — we fall through to basename.
  }
  if (yamlSlug && SLUG_RE.test(yamlSlug)) return yamlSlug

  const segments = projectRoot.split(/[\\/]/).filter(Boolean)
  const base = segments.length > 0 ? segments[segments.length - 1] : ''
  if (base && SLUG_RE.test(base)) return base
  return null
}

/**
 * Read the `project_id` scalar from `<projectRoot>/.cloglog/config.yaml`.
 * Returns null if the file is absent or has no `project_id` field.
 * Used by Guard 3 (T-398): when project_id is set, the legacy global
 * credentials fallback is disabled.
 */
export function resolveProjectId(projectRoot: string): string | null {
  const cfgPath = join(projectRoot, '.cloglog', 'config.yaml')
  try {
    const content = readFileSync(cfgPath, 'utf8')
    const m = content.match(/^project_id:[ \t]*(.+?)[ \t]*(?:#.*)?$/m)
    if (m) {
      let raw = m[1].trim()
      if (
        raw.length >= 2 &&
        ((raw.startsWith('"') && raw.endsWith('"')) ||
          (raw.startsWith("'") && raw.endsWith("'")))
      ) {
        raw = raw.substring(1, raw.length - 1)
      }
      return raw || null
    }
  } catch {
    // Missing config.yaml — no project_id
  }
  return null
}

/**
 * Resolve the project API key from env, per-project file, or legacy global file.
 *
 * @throws {MissingCredentialsError} when none of the sources yields a non-empty key.
 */
export function loadApiKey(opts: LoadApiKeyOptions = {}): string {
  const env = opts.env ?? process.env
  const credentialsPath = opts.credentialsPath ?? DEFAULT_CREDENTIALS_PATH
  const projectCredentialsDir = opts.projectCredentialsDir ?? DEFAULT_PROJECT_CREDENTIALS_DIR
  const startDir = opts.projectRoot ?? process.cwd()

  // 1. Env override.
  const fromEnv = env.CLOGLOG_API_KEY
  if (typeof fromEnv === 'string' && fromEnv.length > 0) return fromEnv

  // 2. Per-project file. Once this file exists, it MUST yield a usable
  //    key; refusing to fall back guards against silently sending the
  //    legacy global file's key (which may belong to another project)
  //    when the per-project file is present-but-broken.
  const projectRoot = findProjectRoot(startDir) ?? startDir
  const slug = resolveProjectSlug(projectRoot)
  let projectCredentialsPath: string | null = null
  if (slug) {
    projectCredentialsPath = join(projectCredentialsDir, slug)
    const result = readKeyFile(projectCredentialsPath)
    if (result.kind === 'present_ok') return result.key
    if (result.kind === 'present_unusable') {
      throw new UnusableProjectCredentialsError(projectCredentialsPath, slug, result.reason)
    }
    // result.kind === 'missing' — Guard 3 (T-398): if project_id is set in
    // config.yaml, refuse the legacy fallback. A missing per-project file
    // on a project-id-scoped checkout means the credentials were never
    // written, not that this is a legacy single-project host. Falling through
    // to ~/.cloglog/credentials would silently authenticate as whatever
    // project owns that file (the antisocial/cloglog incident this task fixes).
    const projectId = resolveProjectId(projectRoot)
    if (projectId) {
      throw new ProjectIdSetMissingCredentialsError(projectId, slug, projectCredentialsPath)
    }
    // project_id not set — legacy single-project host, fallback is safe.
  }

  // 3. Legacy global. Same readKeyFile shape, but a present-but-broken
  //    global file is "missing" for resolution purposes (no per-project
  //    invariant to protect) — surface as MissingCredentialsError below.
  const legacyResult = readKeyFile(credentialsPath)
  if (legacyResult.kind === 'present_ok') return legacyResult.key

  throw new MissingCredentialsError(credentialsPath, projectCredentialsPath, slug)
}

type KeyFileResult =
  | { kind: 'missing' }
  | { kind: 'present_ok'; key: string }
  | { kind: 'present_unusable'; reason: 'unreadable' | 'is_directory' | 'empty_or_no_key' }

/**
 * Read a credentials file with present-but-broken detection. Distinguishes:
 *   - missing (ENOENT) — caller may try the next source
 *   - present but unusable (EACCES/EISDIR/empty) — caller must fail loud
 *     for per-project lookup; the legacy lookup downgrades it to missing
 *     since there is no further source to protect.
 *   - present and OK — returns the key
 */
function readKeyFile(path: string): KeyFileResult {
  let contents: string
  try {
    contents = readFileSync(path, 'utf8')
  } catch (err) {
    const code = (err as NodeJS.ErrnoException).code
    if (code === 'ENOENT') return { kind: 'missing' }
    if (code === 'EACCES') return { kind: 'present_unusable', reason: 'unreadable' }
    if (code === 'EISDIR') return { kind: 'present_unusable', reason: 'is_directory' }
    throw err
  }
  warnIfWorldReadable(path)
  const value = parseCredentialsFile(contents)
  if (value && value.length > 0) return { kind: 'present_ok', key: value }
  return { kind: 'present_unusable', reason: 'empty_or_no_key' }
}

function parseCredentialsFile(contents: string): string | null {
  for (const rawLine of contents.split('\n')) {
    const line = rawLine.trim()
    if (!line || line.startsWith('#')) continue
    const eq = line.indexOf('=')
    if (eq === -1) continue
    const key = line.substring(0, eq).trim()
    if (key !== 'CLOGLOG_API_KEY') continue
    let value = line.substring(eq + 1).trim()
    if (
      value.length >= 2 &&
      ((value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'")))
    ) {
      value = value.substring(1, value.length - 1)
    }
    return value
  }
  return null
}

function warnIfWorldReadable(path: string): void {
  try {
    const mode = statSync(path).mode & 0o777
    if (mode & 0o077) {
      console.error(
        `cloglog-mcp: WARNING ${path} has permissions ${mode.toString(8).padStart(3, '0')}; ` +
          `recommend chmod 600 to keep the project API key off other accounts.`,
      )
    }
  } catch {
    // Permissions check is best-effort; the read above already succeeded.
  }
}
