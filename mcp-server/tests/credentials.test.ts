import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { mkdtempSync, rmSync, writeFileSync, chmodSync, mkdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import {
  DEFAULT_CREDENTIALS_PATH,
  DEFAULT_PROJECT_CREDENTIALS_DIR,
  findProjectRoot,
  loadApiKey,
  MissingCredentialsError,
  resolveProjectSlug,
} from '../src/credentials.js'

describe('loadApiKey', () => {
  let workDir: string
  let credentialsPath: string
  let projectCredentialsDir: string
  let projectRoot: string

  beforeEach(() => {
    workDir = mkdtempSync(join(tmpdir(), 'cloglog-creds-'))
    credentialsPath = join(workDir, 'credentials')
    projectCredentialsDir = join(workDir, 'credentials.d')
    mkdirSync(projectCredentialsDir, { recursive: true })
    // A project root with no .cloglog/config.yaml so slug derivation falls
    // back to basename — keeps existing single-project behaviour exercised.
    projectRoot = join(workDir, 'no-config-project')
    mkdirSync(projectRoot, { recursive: true })
  })

  afterEach(() => {
    rmSync(workDir, { recursive: true, force: true })
  })

  it('uses env CLOGLOG_API_KEY when set', () => {
    const key = loadApiKey({
      env: { CLOGLOG_API_KEY: 'env-supplied-key' },
      credentialsPath,
      projectCredentialsDir,
      projectRoot,
    })
    expect(key).toBe('env-supplied-key')
  })

  it('prefers env over credentials file when both are present', () => {
    writeFileSync(credentialsPath, 'CLOGLOG_API_KEY=from-file\n')
    const key = loadApiKey({
      env: { CLOGLOG_API_KEY: 'from-env' },
      credentialsPath,
      projectCredentialsDir,
      projectRoot,
    })
    expect(key).toBe('from-env')
  })

  it('falls back to credentials file when env is empty', () => {
    writeFileSync(credentialsPath, 'CLOGLOG_API_KEY=file-key-abc\n')
    const key = loadApiKey({
      env: {},
      credentialsPath,
      projectCredentialsDir,
      projectRoot,
    })
    expect(key).toBe('file-key-abc')
  })

  it('treats env empty string as absent', () => {
    writeFileSync(credentialsPath, 'CLOGLOG_API_KEY=file-fallback\n')
    const key = loadApiKey({
      env: { CLOGLOG_API_KEY: '' },
      credentialsPath,
      projectCredentialsDir,
      projectRoot,
    })
    expect(key).toBe('file-fallback')
  })

  it('parses credentials file with comments, blanks, and other vars', () => {
    writeFileSync(
      credentialsPath,
      [
        '# cloglog credentials',
        '',
        'OTHER_VAR=ignored',
        'CLOGLOG_API_KEY=secret-99',
        'TRAILING=also-ignored',
      ].join('\n'),
    )
    const key = loadApiKey({
      env: {},
      credentialsPath,
      projectCredentialsDir,
      projectRoot,
    })
    expect(key).toBe('secret-99')
  })

  it('strips surrounding double quotes from credentials value', () => {
    writeFileSync(credentialsPath, 'CLOGLOG_API_KEY="quoted-value"\n')
    const key = loadApiKey({
      env: {},
      credentialsPath,
      projectCredentialsDir,
      projectRoot,
    })
    expect(key).toBe('quoted-value')
  })

  it('strips surrounding single quotes from credentials value', () => {
    writeFileSync(credentialsPath, "CLOGLOG_API_KEY='single-quoted'\n")
    const key = loadApiKey({
      env: {},
      credentialsPath,
      projectCredentialsDir,
      projectRoot,
    })
    expect(key).toBe('single-quoted')
  })

  it('throws MissingCredentialsError naming the credentials path when nothing is set', () => {
    expect(() =>
      loadApiKey({ env: {}, credentialsPath, projectCredentialsDir, projectRoot }),
    ).toThrow(MissingCredentialsError)
    try {
      loadApiKey({ env: {}, credentialsPath, projectCredentialsDir, projectRoot })
    } catch (err) {
      expect(err).toBeInstanceOf(MissingCredentialsError)
      const msg = (err as Error).message
      expect(msg).toContain(credentialsPath)
      expect(msg).toContain('CLOGLOG_API_KEY')
      expect(msg).toContain('chmod 600')
    }
  })

  it('throws MissingCredentialsError when file exists but does not define the key', () => {
    writeFileSync(credentialsPath, '# only a comment\nOTHER=value\n')
    expect(() =>
      loadApiKey({ env: {}, credentialsPath, projectCredentialsDir, projectRoot }),
    ).toThrow(MissingCredentialsError)
  })

  it('throws MissingCredentialsError when file defines the key as empty', () => {
    writeFileSync(credentialsPath, 'CLOGLOG_API_KEY=\n')
    expect(() =>
      loadApiKey({ env: {}, credentialsPath, projectCredentialsDir, projectRoot }),
    ).toThrow(MissingCredentialsError)
  })

  it('treats unreadable credentials path as missing', () => {
    const dirAsPath = join(workDir, 'nope-dir')
    mkdirSync(dirAsPath)
    expect(() =>
      loadApiKey({
        env: {},
        credentialsPath: dirAsPath,
        projectCredentialsDir,
        projectRoot,
      }),
    ).toThrow(MissingCredentialsError)
  })

  it('reads credentials file even when permissions are loose (warns to stderr)', () => {
    writeFileSync(credentialsPath, 'CLOGLOG_API_KEY=loose-perms\n')
    chmodSync(credentialsPath, 0o644)
    const key = loadApiKey({
      env: {},
      credentialsPath,
      projectCredentialsDir,
      projectRoot,
    })
    expect(key).toBe('loose-perms')
  })

  it('default credentials path is under the user home directory', () => {
    expect(DEFAULT_CREDENTIALS_PATH).toMatch(/\.cloglog[/\\]credentials$/)
  })

  it('default project credentials dir is under the user home directory', () => {
    expect(DEFAULT_PROJECT_CREDENTIALS_DIR).toMatch(/\.cloglog[/\\]credentials\.d$/)
  })
})

describe('per-project credential resolution (T-382)', () => {
  let workDir: string
  let projectCredentialsDir: string
  let legacyCredentialsPath: string

  beforeEach(() => {
    workDir = mkdtempSync(join(tmpdir(), 'cloglog-projcreds-'))
    projectCredentialsDir = join(workDir, 'credentials.d')
    legacyCredentialsPath = join(workDir, 'credentials')
    mkdirSync(projectCredentialsDir, { recursive: true })
  })

  afterEach(() => {
    rmSync(workDir, { recursive: true, force: true })
  })

  function makeProject(name: string, projectField: string | null): string {
    const root = join(workDir, name)
    mkdirSync(join(root, '.cloglog'), { recursive: true })
    if (projectField !== null) {
      writeFileSync(
        join(root, '.cloglog', 'config.yaml'),
        `project: ${projectField}\nbackend_url: http://127.0.0.1:8001\n`,
      )
    }
    return root
  }

  it('routes the right key to the right project root via per-project credentials.d', () => {
    const projectA = makeProject('alpha-checkout', 'alpha')
    const projectB = makeProject('beta-checkout', 'beta')
    writeFileSync(join(projectCredentialsDir, 'alpha'), 'CLOGLOG_API_KEY=alpha-key\n')
    writeFileSync(join(projectCredentialsDir, 'beta'), 'CLOGLOG_API_KEY=beta-key\n')
    writeFileSync(legacyCredentialsPath, 'CLOGLOG_API_KEY=legacy-fallback\n')

    expect(
      loadApiKey({
        env: {},
        credentialsPath: legacyCredentialsPath,
        projectCredentialsDir,
        projectRoot: projectA,
      }),
    ).toBe('alpha-key')

    expect(
      loadApiKey({
        env: {},
        credentialsPath: legacyCredentialsPath,
        projectCredentialsDir,
        projectRoot: projectB,
      }),
    ).toBe('beta-key')
  })

  it('falls back to legacy credentials when no per-project file exists (single-project hosts unaffected)', () => {
    const project = makeProject('only-project', 'only')
    writeFileSync(legacyCredentialsPath, 'CLOGLOG_API_KEY=legacy-only\n')

    expect(
      loadApiKey({
        env: {},
        credentialsPath: legacyCredentialsPath,
        projectCredentialsDir,
        projectRoot: project,
      }),
    ).toBe('legacy-only')
  })

  it('env override beats both per-project and legacy files', () => {
    const project = makeProject('env-wins', 'envwins')
    writeFileSync(join(projectCredentialsDir, 'envwins'), 'CLOGLOG_API_KEY=project-key\n')
    writeFileSync(legacyCredentialsPath, 'CLOGLOG_API_KEY=legacy-key\n')

    expect(
      loadApiKey({
        env: { CLOGLOG_API_KEY: 'env-key' },
        credentialsPath: legacyCredentialsPath,
        projectCredentialsDir,
        projectRoot: project,
      }),
    ).toBe('env-key')
  })

  it('walks up from a worktree subdir to find the project root', () => {
    const project = makeProject('with-worktree', 'wtproj')
    const worktree = join(project, '.claude', 'worktrees', 'wt-foo')
    mkdirSync(worktree, { recursive: true })
    writeFileSync(join(projectCredentialsDir, 'wtproj'), 'CLOGLOG_API_KEY=wtproj-key\n')

    expect(
      loadApiKey({
        env: {},
        credentialsPath: legacyCredentialsPath,
        projectCredentialsDir,
        projectRoot: worktree,
      }),
    ).toBe('wtproj-key')
  })

  it('falls back to basename slug when config.yaml has no project field', () => {
    const project = makeProject('basename-only', null)
    // Config exists (so findProjectRoot returns this dir) but has no project key.
    writeFileSync(join(project, '.cloglog', 'config.yaml'), 'backend_url: http://x\n')
    writeFileSync(join(projectCredentialsDir, 'basename-only'), 'CLOGLOG_API_KEY=base-key\n')

    expect(
      loadApiKey({
        env: {},
        credentialsPath: legacyCredentialsPath,
        projectCredentialsDir,
        projectRoot: project,
      }),
    ).toBe('base-key')
  })

  it('rejects path-traversal slugs and falls through to legacy', () => {
    const project = makeProject('bad-slug', '../escape')
    writeFileSync(legacyCredentialsPath, 'CLOGLOG_API_KEY=safe-legacy\n')
    // Even if an attacker creates a file named matching the traversal, slug
    // validation rejects the field outright and we fall back via basename.
    writeFileSync(join(projectCredentialsDir, 'bad-slug'), 'CLOGLOG_API_KEY=basename-key\n')

    // Basename `bad-slug` is valid, so we resolve via that — NOT via the
    // rejected `../escape` field. Pin: traversal in project field never wins.
    expect(
      loadApiKey({
        env: {},
        credentialsPath: legacyCredentialsPath,
        projectCredentialsDir,
        projectRoot: project,
      }),
    ).toBe('basename-key')
  })

  it('error message lists all paths tried (env, per-project, legacy)', () => {
    const project = makeProject('missing-everywhere', 'missingeverywhere')
    try {
      loadApiKey({
        env: {},
        credentialsPath: legacyCredentialsPath,
        projectCredentialsDir,
        projectRoot: project,
      })
      throw new Error('expected MissingCredentialsError')
    } catch (err) {
      expect(err).toBeInstanceOf(MissingCredentialsError)
      const msg = (err as Error).message
      expect(msg).toContain('CLOGLOG_API_KEY')
      expect(msg).toContain(join(projectCredentialsDir, 'missingeverywhere'))
      expect(msg).toContain(legacyCredentialsPath)
      expect(msg).toContain('slug=missingeverywhere')
    }
  })
})

describe('resolveProjectSlug', () => {
  let workDir: string

  beforeEach(() => {
    workDir = mkdtempSync(join(tmpdir(), 'cloglog-slug-'))
  })

  afterEach(() => {
    rmSync(workDir, { recursive: true, force: true })
  })

  it('reads project: from .cloglog/config.yaml', () => {
    const root = join(workDir, 'myproj')
    mkdirSync(join(root, '.cloglog'), { recursive: true })
    writeFileSync(join(root, '.cloglog', 'config.yaml'), 'project: myproj\n')
    expect(resolveProjectSlug(root)).toBe('myproj')
  })

  it('handles trailing comments and quotes in the project field', () => {
    const root = join(workDir, 'quoted')
    mkdirSync(join(root, '.cloglog'), { recursive: true })
    writeFileSync(
      join(root, '.cloglog', 'config.yaml'),
      'project: "fancy_proj"   # the slug\n',
    )
    expect(resolveProjectSlug(root)).toBe('fancy_proj')
  })

  it('falls back to basename when config.yaml absent', () => {
    const root = join(workDir, 'just-a-dir')
    mkdirSync(root)
    expect(resolveProjectSlug(root)).toBe('just-a-dir')
  })

  it('returns null when both project field and basename are slug-invalid', () => {
    // Empty path component — basename comes back as '', which fails the regex.
    expect(resolveProjectSlug('')).toBeNull()
  })
})

describe('findProjectRoot', () => {
  let workDir: string

  beforeEach(() => {
    workDir = mkdtempSync(join(tmpdir(), 'cloglog-find-'))
  })

  afterEach(() => {
    rmSync(workDir, { recursive: true, force: true })
  })

  it('returns the cwd when it has .cloglog/config.yaml', () => {
    const root = join(workDir, 'proj')
    mkdirSync(join(root, '.cloglog'), { recursive: true })
    writeFileSync(join(root, '.cloglog', 'config.yaml'), 'project: x\n')
    expect(findProjectRoot(root)).toBe(root)
  })

  it('walks up to find the project root from a nested subdir', () => {
    const root = join(workDir, 'proj')
    const nested = join(root, 'a', 'b', 'c')
    mkdirSync(join(root, '.cloglog'), { recursive: true })
    mkdirSync(nested, { recursive: true })
    writeFileSync(join(root, '.cloglog', 'config.yaml'), 'project: x\n')
    expect(findProjectRoot(nested)).toBe(root)
  })

  it('returns null when no ancestor has a config.yaml', () => {
    const stray = join(workDir, 'stray')
    mkdirSync(stray)
    expect(findProjectRoot(stray)).toBeNull()
  })
})
