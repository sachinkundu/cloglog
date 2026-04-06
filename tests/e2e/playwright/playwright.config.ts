import { defineConfig } from '@playwright/test';
import path from 'path';

const TEST_DB_URL = 'postgresql+asyncpg://cloglog:cloglog_dev@localhost:5432/cloglog_e2e_test';
const E2E_BACKEND_PORT = 8001;
const E2E_FRONTEND_PORT = 5174;

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
