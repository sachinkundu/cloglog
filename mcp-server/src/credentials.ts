/**
 * Credential resolution for the cloglog MCP server.
 *
 * The project API key (`CLOGLOG_API_KEY`) MUST live outside of any per-worktree
 * file so that processes inside a worktree cannot read it from disk and bypass
 * the "agents talk to the backend only via MCP" rule.
 *
 * Resolution order:
 *   1. `process.env.CLOGLOG_API_KEY` (set by the operator, e.g. in their shell rc).
 *   2. `~/.cloglog/credentials` — a key=value file with mode 0600.
 *
 * If neither source yields a non-empty key, `loadApiKey` throws
 * `MissingCredentialsError` with an actionable message.
 */

import { readFileSync, statSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

export const DEFAULT_CREDENTIALS_PATH = join(homedir(), '.cloglog', 'credentials')

export class MissingCredentialsError extends Error {
  constructor(public readonly credentialsPath: string) {
    super(
      [
        `cloglog-mcp: CLOGLOG_API_KEY is not set and no usable credentials file was found at ${credentialsPath}.`,
        '',
        'Fix this by either:',
        '  1) Exporting CLOGLOG_API_KEY in the shell that launches the MCP server, OR',
        `  2) Creating ${credentialsPath} with the project key:`,
        '       mkdir -p ~/.cloglog',
        '       printf "CLOGLOG_API_KEY=<your-project-key>\\n" > ~/.cloglog/credentials',
        '       chmod 600 ~/.cloglog/credentials',
        '',
        'See docs/setup-credentials.md.',
      ].join('\n'),
    )
    this.name = 'MissingCredentialsError'
  }
}

export interface LoadApiKeyOptions {
  credentialsPath?: string
  env?: NodeJS.ProcessEnv
}

/**
 * Resolve the project API key from env or `~/.cloglog/credentials`.
 *
 * @throws {MissingCredentialsError} when neither source provides a non-empty key.
 */
export function loadApiKey(opts: LoadApiKeyOptions = {}): string {
  const env = opts.env ?? process.env
  const credentialsPath = opts.credentialsPath ?? DEFAULT_CREDENTIALS_PATH

  const fromEnv = env.CLOGLOG_API_KEY
  if (typeof fromEnv === 'string' && fromEnv.length > 0) {
    return fromEnv
  }

  let contents: string
  try {
    contents = readFileSync(credentialsPath, 'utf8')
  } catch (err) {
    const code = (err as NodeJS.ErrnoException).code
    if (code === 'ENOENT' || code === 'EACCES' || code === 'EISDIR') {
      throw new MissingCredentialsError(credentialsPath)
    }
    throw err
  }

  warnIfWorldReadable(credentialsPath)

  const fromFile = parseCredentialsFile(contents)
  if (fromFile && fromFile.length > 0) {
    return fromFile
  }

  throw new MissingCredentialsError(credentialsPath)
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
