import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright config for MaxSurge E2E.
 *
 * ENV:
 *   BASE_URL   — target host, default https://maxsurge.ru (override for local: http://localhost:8090)
 *   ADMIN_EMAIL, ADMIN_PASSWORD — for login flow tests
 *   CI         — enables junit reporter + retries
 */
export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI
    ? [['junit', { outputFile: 'test-results/junit.xml' }], ['html', { open: 'never' }]]
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
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    // Uncomment when mobile responsive tests are needed:
    // { name: 'mobile', use: { ...devices['iPhone 13'] } },
  ],
});
