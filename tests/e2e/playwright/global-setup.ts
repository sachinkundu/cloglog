/**
 * Playwright global setup: creates an isolated test database for E2E tests.
 * Clones the schema from the dev database using pg_dump (no data).
 * The backend webServer is started with DATABASE_URL pointing to this DB.
 * Global teardown drops the database after all tests complete.
 */
import { execFileSync } from 'child_process';

const PG_HOST = process.env.PG_HOST ?? 'localhost';
const PG_PORT = process.env.PG_PORT ?? '5432';
const PG_USER = process.env.PG_USER ?? 'cloglog';
const PG_PASSWORD = process.env.PG_PASSWORD ?? 'cloglog_dev';
// Use worktree DB name if available (set by scripts/worktree-ports.sh), otherwise E2E default
const TEST_DB = process.env.WORKTREE_DB_NAME ?? 'cloglog_e2e_test';

function psql(sql: string, db = 'postgres') {
  execFileSync('psql', ['-h', PG_HOST, '-p', PG_PORT, '-U', PG_USER, '-d', db, '-c', sql], {
    stdio: 'pipe',
    env: { ...process.env, PGPASSWORD: PG_PASSWORD },
  });
}

export default async function globalSetup() {
  console.log(`\n[e2e] Creating test database: ${TEST_DB}`);

  // Drop if exists from a previous interrupted run
  try {
    psql(`DROP DATABASE IF EXISTS ${TEST_DB};`);
  } catch {
    // Ignore
  }

  // Create fresh test database
  psql(`CREATE DATABASE ${TEST_DB};`);

  // Clone schema from dev database (schema only, no data)
  const schema = execFileSync('pg_dump', [
    '-h', PG_HOST, '-p', PG_PORT, '-U', PG_USER,
    '--schema-only', '--no-owner', '--no-privileges',
    'cloglog',
  ], {
    env: { ...process.env, PGPASSWORD: PG_PASSWORD },
  });

  execFileSync('psql', ['-h', PG_HOST, '-p', PG_PORT, '-U', PG_USER, '-d', TEST_DB], {
    input: schema,
    env: { ...process.env, PGPASSWORD: PG_PASSWORD },
    stdio: ['pipe', 'pipe', 'pipe'],
  });

  console.log(`[e2e] Test database ready: ${TEST_DB}`);
}
