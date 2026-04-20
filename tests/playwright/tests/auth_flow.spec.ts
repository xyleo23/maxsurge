import { test, expect, Page } from '@playwright/test';

/**
 * Auth flow tests — each test uses its own context (no storageState).
 * Runs serially in CI to avoid hitting rate-limit on admin email.
 */

const EMAIL = process.env.ADMIN_EMAIL || '';
const PASSWORD = process.env.ADMIN_PASSWORD || '';
const hasCreds = Boolean(EMAIL && PASSWORD);

async function login(page: Page): Promise<void> {
  await page.goto('/login');
  await page.locator('input[name="email"]').fill(EMAIL);
  await page.locator('input[name="password"]').fill(PASSWORD);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL(/\/app\//, { timeout: 15_000 });
}

test.describe.configure({ mode: 'serial' });

test.describe('Authentication', () => {
  test.skip(!hasCreds, 'ADMIN_EMAIL / ADMIN_PASSWORD required');

  test('login with valid credentials lands on /app/*', async ({ page }) => {
    await login(page);
    expect(page.url()).toContain('/app/');
  });

  test('accessing /app/admin/ without auth redirects to login', async ({ request }) => {
    const r = await request.get('/app/admin/', { maxRedirects: 0 });
    expect([301, 302, 303, 307, 401]).toContain(r.status());
  });

  test('bad login stays on /login', async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[name="email"]').fill('nobody@example.invalid');
    await page.locator('input[name="password"]').fill('wrongpassword123456');
    await page.locator('button[type="submit"]').click();
    await page.waitForTimeout(1000);
    expect(page.url()).toMatch(/\/login/);
  });

  test('logout clears session', async ({ page }) => {
    await login(page);
    // Try to find logout; prod template may use link or form
    const logoutLink = page.getByRole('link', { name: /выход|logout/i }).first();
    const logoutForm = page.locator('form[action*="logout"] button').first();
    if (await logoutLink.isVisible().catch(() => false)) {
      await logoutLink.click();
    } else if (await logoutForm.isVisible().catch(() => false)) {
      await logoutForm.click();
    } else {
      await page.goto('/auth/logout');
    }
    await page.waitForTimeout(500);
    // After logout, hitting /app/ should redirect to /login
    const resp = await page.goto('/app/', { waitUntil: 'domcontentloaded' });
    // Final URL should be /login or similar
    expect(page.url()).toMatch(/login|^https?:\/\/[^\/]+\/?$/);
  });
});
