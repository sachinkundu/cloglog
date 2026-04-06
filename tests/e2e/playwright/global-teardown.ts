/**
 * Playwright global teardown: drops the isolated test database.
 */
import { execFileSync } from 'child_process';

const PG_HOST = process.env.PG_HOST ?? 'localhost';
const PG_PORT = process.env.PG_PORT ?? '5432';
const PG_USER = 'cloglog';
const PG_PASSWORD = 'cloglog_dev';
const TEST_DB = 'cloglog_e2e_test';

function psql(sql: string, db = 'postgres') {
  execFileSync('psql', ['-h', PG_HOST, '-p', PG_PORT, '-U', PG_USER, '-d', db, '-c', sql], {
    stdio: 'pipe',
    env: { ...process.env, PGPASSWORD: PG_PASSWORD },
  });
}

export default async function globalTeardown() {
  console.log(`\n[e2e] Dropping test database: ${TEST_DB}`);
  try {
    // Terminate active connections before dropping
    psql(`SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${TEST_DB}' AND pid <> pg_backend_pid();`);
    psql(`DROP DATABASE IF EXISTS ${TEST_DB};`);
    console.log(`[e2e] Test database dropped: ${TEST_DB}`);
  } catch {
    console.warn(`[e2e] Warning: could not drop test database ${TEST_DB} — clean up manually`);
  }
}
