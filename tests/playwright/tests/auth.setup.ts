import { test as setup, expect } from '@playwright/test';

const EMAIL = process.env.ADMIN_EMAIL || '';
const PASSWORD = process.env.ADMIN_PASSWORD || '';
const authFile = '.auth/admin.json';

setup('login once and save state', async ({ page }) => {
  setup.skip(!EMAIL || !PASSWORD, 'ADMIN_EMAIL / ADMIN_PASSWORD env required');

  await page.goto('/login');
  await page.locator('input[name="email"]').fill(EMAIL);
  await page.locator('input[name="password"]').fill(PASSWORD);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL(/\/app\//, { timeout: 15_000 });

  // Sanity check: we're inside /app/*
  expect(page.url()).toContain('/app/');

  await page.context().storageState({ path: authFile });
});
