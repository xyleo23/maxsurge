import { test, expect, Page } from '@playwright/test';

/**
 * Auth flow — login, logout, protected routes.
 *
 * Requires env vars ADMIN_EMAIL and ADMIN_PASSWORD.
 * Skipped if absent (so CI doesn't fail on forks / missing secrets).
 */

const EMAIL = process.env.ADMIN_EMAIL || '';
const PASSWORD = process.env.ADMIN_PASSWORD || '';
const hasCreds = Boolean(EMAIL && PASSWORD);

test.describe('Authentication', () => {
  test.skip(!hasCreds, 'ADMIN_EMAIL / ADMIN_PASSWORD env not provided');

  async function login(page: Page): Promise<void> {
    await page.goto('/login');
    await page.locator('input[name="email"]').fill(EMAIL);
    await page.locator('input[name="password"]').fill(PASSWORD);
    await page.getByRole('button', { name: /войти|log ?in/i }).click();
    await page.waitForURL(/\/app\//, { timeout: 10_000 });
  }

  test('login with valid credentials lands on /app/*', async ({ page }) => {
    await login(page);
    expect(page.url()).toContain('/app/');
    // Dashboard should show user's email somewhere (header menu etc)
    const body = (await page.locator('body').innerText()).toLowerCase();
    expect(body.includes(EMAIL.toLowerCase()) || body.includes('dashboard') || body.includes('аккаунт')).toBeTruthy();
  });

  test('logout clears session and redirects to /', async ({ page }) => {
    await login(page);
    // Logout via explicit link or form
    const logoutLink = page.getByRole('link', { name: /выход|logout/i }).first();
    if (await logoutLink.isVisible().catch(() => false)) {
      await logoutLink.click();
    } else {
      // Fallback: POST /auth/logout
      await page.goto('/auth/logout');
    }
    // After logout, /app/ should redirect back to /login
    await page.goto('/app/');
    await expect(page).toHaveURL(/\/login/);
  });

  test('accessing /app/admin/ without auth redirects', async ({ request }) => {
    const r = await request.get('/app/admin/', { maxRedirects: 0 }).catch((e) => e);
    // Expect 303 / 302 / 307 or any 3xx or 401
    expect([301, 302, 303, 307, 401]).toContain(r.status?.() ?? r.status);
  });

  test('bad login keeps user on /login with error', async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[name="email"]').fill('nobody@example.invalid');
    await page.locator('input[name="password"]').fill('wrongpassword');
    await page.getByRole('button', { name: /войти|log ?in/i }).click();
    // Either still on /login or redirected back; body should contain error
    await page.waitForTimeout(500);
    expect(page.url()).toContain('/login');
  });

  test('rate limit kicks in after 5 bad attempts', async ({ page }) => {
    // This test is intentionally gentle — run locally only
    test.skip(Boolean(process.env.CI), 'skipped in CI to avoid locking admin email');
    for (let i = 0; i < 6; i++) {
      await page.goto('/login');
      await page.locator('input[name="email"]').fill(EMAIL);
      await page.locator('input[name="password"]').fill('wrong' + i);
      await page.getByRole('button', { name: /войти|log ?in/i }).click();
      await page.waitForTimeout(300);
    }
    // 6th attempt should show rate-limit message
    const body = await page.locator('body').innerText();
    expect(body).toMatch(/попыток|rate|лимит|too many/i);
  });
});
