import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { mkdtempSync, rmSync, writeFileSync, chmodSync, mkdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import {
  DEFAULT_CREDENTIALS_PATH,
  loadApiKey,
  MissingCredentialsError,
} from '../src/credentials.js'

describe('loadApiKey', () => {
  let workDir: string
  let credentialsPath: string

  beforeEach(() => {
    workDir = mkdtempSync(join(tmpdir(), 'cloglog-creds-'))
    credentialsPath = join(workDir, 'credentials')
  })

  afterEach(() => {
    rmSync(workDir, { recursive: true, force: true })
  })

  it('uses env CLOGLOG_API_KEY when set', () => {
    const key = loadApiKey({
      env: { CLOGLOG_API_KEY: 'env-supplied-key' },
      credentialsPath,
    })
    expect(key).toBe('env-supplied-key')
  })

  it('prefers env over credentials file when both are present', () => {
    writeFileSync(credentialsPath, 'CLOGLOG_API_KEY=from-file\n')
    const key = loadApiKey({
      env: { CLOGLOG_API_KEY: 'from-env' },
      credentialsPath,
    })
    expect(key).toBe('from-env')
  })

  it('falls back to credentials file when env is empty', () => {
    writeFileSync(credentialsPath, 'CLOGLOG_API_KEY=file-key-abc\n')
    const key = loadApiKey({ env: {}, credentialsPath })
    expect(key).toBe('file-key-abc')
  })

  it('treats env empty string as absent', () => {
    writeFileSync(credentialsPath, 'CLOGLOG_API_KEY=file-fallback\n')
    const key = loadApiKey({
      env: { CLOGLOG_API_KEY: '' },
      credentialsPath,
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
    const key = loadApiKey({ env: {}, credentialsPath })
    expect(key).toBe('secret-99')
  })

  it('strips surrounding double quotes from credentials value', () => {
    writeFileSync(credentialsPath, 'CLOGLOG_API_KEY="quoted-value"\n')
    const key = loadApiKey({ env: {}, credentialsPath })
    expect(key).toBe('quoted-value')
  })

  it('strips surrounding single quotes from credentials value', () => {
    writeFileSync(credentialsPath, "CLOGLOG_API_KEY='single-quoted'\n")
    const key = loadApiKey({ env: {}, credentialsPath })
    expect(key).toBe('single-quoted')
  })

  it('throws MissingCredentialsError naming the credentials path when nothing is set', () => {
    expect(() => loadApiKey({ env: {}, credentialsPath })).toThrow(
      MissingCredentialsError,
    )
    try {
      loadApiKey({ env: {}, credentialsPath })
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
    expect(() => loadApiKey({ env: {}, credentialsPath })).toThrow(
      MissingCredentialsError,
    )
  })

  it('throws MissingCredentialsError when file defines the key as empty', () => {
    writeFileSync(credentialsPath, 'CLOGLOG_API_KEY=\n')
    expect(() => loadApiKey({ env: {}, credentialsPath })).toThrow(
      MissingCredentialsError,
    )
  })

  it('treats unreadable credentials path as missing', () => {
    const dirAsPath = join(workDir, 'nope-dir')
    mkdirSync(dirAsPath)
    expect(() =>
      loadApiKey({ env: {}, credentialsPath: dirAsPath }),
    ).toThrow(MissingCredentialsError)
  })

  it('reads credentials file even when permissions are loose (warns to stderr)', () => {
    writeFileSync(credentialsPath, 'CLOGLOG_API_KEY=loose-perms\n')
    chmodSync(credentialsPath, 0o644)
    const key = loadApiKey({ env: {}, credentialsPath })
    expect(key).toBe('loose-perms')
  })

  it('default credentials path is under the user home directory', () => {
    expect(DEFAULT_CREDENTIALS_PATH).toMatch(/\.cloglog[/\\]credentials$/)
  })
})
