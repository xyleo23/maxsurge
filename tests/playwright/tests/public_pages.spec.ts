import { test, expect } from '@playwright/test';

/**
 * Public pages — smoke that anonymous visitor sees what they should.
 *
 * Covers roughly the same ground as scripts/e2e_smoke.sh but checks
 * rendered DOM (not just HTTP 200).
 */

test.describe('Public pages', () => {
  test('landing page renders key CTAs', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveTitle(/MaxSurge/);
    // Hero CTA
    await expect(page.getByRole('link', { name: /Начать|Попробовать|Регистр/i }).first()).toBeVisible();
    // Pricing mentioned somewhere
    await expect(page.locator('body')).toContainText(/Start|Basic|Pro/);
  });

  test('login page has email+password+submit', async ({ page }) => {
    await page.goto('/login');
    await expect(page.getByLabel(/email|почта/i).first()).toBeVisible();
    await expect(page.getByLabel(/пароль|password/i).first()).toBeVisible();
    await expect(page.getByRole('button', { name: /войти|log ?in/i })).toBeVisible();
  });

  test('register page has form + terms acceptance link', async ({ page }) => {
    await page.goto('/register');
    await expect(page.locator('input[name="email"]')).toBeVisible();
    await expect(page.locator('input[name="password"]')).toBeVisible();
    await expect(page.getByRole('link', { name: /услов|terms/i }).first()).toBeVisible();
  });

  test('terms page contains ИП and НПД', async ({ page }) => {
    await page.goto('/terms');
    await expect(page.locator('body')).toContainText(/Беляев/);
    await expect(page.locator('body')).toContainText(/НПД/);
    await expect(page.locator('body')).toContainText(/233304095766/); // ИНН
  });

  test('privacy page cites 152-ФЗ', async ({ page }) => {
    await page.goto('/privacy');
    await expect(page.locator('body')).toContainText(/152-ФЗ/);
    await expect(page.locator('body')).toContainText(/bcrypt/);
  });

  test('status page shows operational state', async ({ page }) => {
    await page.goto('/status');
    const bodyText = (await page.locator('body').innerText()).toLowerCase();
    expect(bodyText).toMatch(/статус|работ|ok/);
  });

  test('/openapi.json is closed in prod', async ({ request }) => {
    const r = await request.get('/openapi.json');
    expect(r.status()).toBe(404);
  });

  test('/api/docs is closed in prod', async ({ request }) => {
    const r = await request.get('/api/docs');
    expect(r.status()).toBe(404);
  });

  test('/metrics requires Basic auth', async ({ request }) => {
    const r = await request.get('/metrics');
    expect(r.status()).toBe(401);
    expect(r.headers()['www-authenticate']).toContain('Basic');
  });

  test('security headers present on landing', async ({ request }) => {
    const r = await request.get('/');
    const h = r.headers();
    expect(h['strict-transport-security']).toBeTruthy();
    expect(h['x-content-type-options']).toBe('nosniff');
    expect(h['x-frame-options']).toMatch(/DENY|SAMEORIGIN/);
  });
});
