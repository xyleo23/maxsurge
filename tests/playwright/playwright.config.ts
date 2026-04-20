import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright config for MaxSurge E2E.
 *
 * ENV:
 *   BASE_URL       target host (default https://maxsurge.ru)
 *   ADMIN_EMAIL    for setup (login once, save storage state)
 *   ADMIN_PASSWORD
 *   CI             enables junit + retries + serial
 */
export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : 2,  // Serial in CI to avoid rate-limit
  reporter: process.env.CI
    ? [['junit', { outputFile: 'test-results/junit.xml' }], ['html', { open: 'never' }], ['list']]
    : [['html', { open: 'on-failure' }], ['list']],

  use: {
    baseURL: process.env.BASE_URL || 'https://maxsurge.ru',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    ignoreHTTPSErrors: true,
    locale: 'ru-RU',
    timezoneId: 'Europe/Moscow',
  },

  projects: [
    // 1. Setup: login once, save state
    {
      name: 'setup',
      testMatch: /auth\.setup\.ts/,
    },

    // 2. Public pages — no auth needed
    {
      name: 'public',
      testMatch: /public_pages\.spec\.ts/,
      use: { ...devices['Desktop Chrome'] },
    },

    // 3. Auth tests — run raw login/logout without storageState
    {
      name: 'auth',
      testMatch: /auth_flow\.spec\.ts/,
      use: { ...devices['Desktop Chrome'] },
      // Not dependent on setup — tests its own login/logout from scratch
    },

    // 4. App tests — use stored session from setup
    {
      name: 'app',
      testMatch: /accounts_ui\.spec\.ts/,
      use: {
        ...devices['Desktop Chrome'],
        storageState: '.auth/admin.json',
      },
      dependencies: ['setup'],
    },
  ],
});
