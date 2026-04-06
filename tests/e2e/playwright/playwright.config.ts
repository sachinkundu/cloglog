import { defineConfig } from '@playwright/test';
import path from 'path';

// Read from worktree .env if available, otherwise use E2E defaults.
// In worktrees, scripts/worktree-ports.sh sets these via .env.
const E2E_BACKEND_PORT = parseInt(process.env.BACKEND_PORT ?? '8001', 10);
const E2E_FRONTEND_PORT = parseInt(process.env.FRONTEND_PORT ?? '5174', 10);
const TEST_DB_NAME = process.env.WORKTREE_DB_NAME ?? 'cloglog_e2e_test';
const TEST_DB_URL = process.env.DATABASE_URL
  ? process.env.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://')
  : `postgresql+asyncpg://cloglog:cloglog_dev@localhost:5432/${TEST_DB_NAME}`;

// Resolve absolute paths from the config file location
const REPO_ROOT = path.resolve(__dirname, '../../..');
const FRONTEND_DIR = path.resolve(REPO_ROOT, 'frontend');

export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  expect: { timeout: 5_000 },
  retries: 1,
  workers: 1,
  reporter: [['html', { open: 'never' }], ['list']],
  globalSetup: './global-setup.ts',
  globalTeardown: './global-teardown.ts',
  use: {
    baseURL: `http://localhost:${E2E_FRONTEND_PORT}`,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: { browserName: 'chromium' } },
  ],
  webServer: [
    {
      command: `uv run uvicorn src.gateway.app:create_app --factory --host 0.0.0.0 --port ${E2E_BACKEND_PORT}`,
      url: `http://localhost:${E2E_BACKEND_PORT}/health`,
      cwd: REPO_ROOT,
      reuseExistingServer: false,
      timeout: 30_000,
      env: {
        ...process.env,
        DATABASE_URL: TEST_DB_URL,
        // Suppress desktop notifications (notify-send) during E2E tests
        DISPLAY: '',
      },
    },
    {
      command: `npx vite --port ${E2E_FRONTEND_PORT}`,
      url: `http://localhost:${E2E_FRONTEND_PORT}`,
      cwd: FRONTEND_DIR,
      reuseExistingServer: false,
      timeout: 30_000,
      env: {
        ...process.env,
        VITE_API_URL: `http://localhost:${E2E_BACKEND_PORT}/api/v1`,
      },
    },
  ],
});
