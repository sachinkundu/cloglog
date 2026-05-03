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

  // 2. Per-project file.
  const projectRoot = findProjectRoot(startDir) ?? startDir
  const slug = resolveProjectSlug(projectRoot)
  let projectCredentialsPath: string | null = null
  if (slug) {
    projectCredentialsPath = join(projectCredentialsDir, slug)
    const fromProject = tryReadKeyFile(projectCredentialsPath)
    if (fromProject) return fromProject
  }

  // 3. Legacy global.
  const fromLegacy = tryReadKeyFile(credentialsPath)
  if (fromLegacy) return fromLegacy

  throw new MissingCredentialsError(credentialsPath, projectCredentialsPath, slug)
}

function tryReadKeyFile(path: string): string | null {
  let contents: string
  try {
    contents = readFileSync(path, 'utf8')
  } catch (err) {
    const code = (err as NodeJS.ErrnoException).code
    if (code === 'ENOENT' || code === 'EACCES' || code === 'EISDIR') return null
    throw err
  }
  warnIfWorldReadable(path)
  const value = parseCredentialsFile(contents)
  return value && value.length > 0 ? value : null
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
