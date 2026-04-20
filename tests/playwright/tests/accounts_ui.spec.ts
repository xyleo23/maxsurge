import { test, expect, Page } from '@playwright/test';

/**
 * /app/accounts/ UI — role dialog, bulk select, toggle, inline comment.
 *
 * Needs auth. Creates and deletes its own role to avoid polluting user data.
 * Does NOT add MAX accounts (would trigger real MAX API / rate limits).
 */

const EMAIL = process.env.ADMIN_EMAIL || '';
const PASSWORD = process.env.ADMIN_PASSWORD || '';
const hasCreds = Boolean(EMAIL && PASSWORD);

async function login(page: Page): Promise<void> {
  await page.goto('/login');
  await page.locator('input[name="email"]').fill(EMAIL);
  await page.locator('input[name="password"]').fill(PASSWORD);
  await page.getByRole('button', { name: /войти|log ?in/i }).click();
  await page.waitForURL(/\/app\//, { timeout: 10_000 });
}

test.describe('Accounts page UI', () => {
  test.skip(!hasCreds, 'ADMIN_EMAIL / ADMIN_PASSWORD env not provided');

  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.goto('/app/accounts/');
  });

  test('roles modal: create, rename, delete', async ({ page }) => {
    const roleName = `E2E-${Date.now()}`;

    // Open modal
    await page.getByRole('button', { name: /Роли/ }).click();
    await expect(page.getByText('Роли аккаунтов')).toBeVisible();

    // Create
    await page.locator('input[placeholder*="Название роли"]').fill(roleName);
    await page.locator('input[placeholder*="Название роли"]').press('Enter');

    // New role should appear in list
    await expect(page.locator(`text=${roleName}`)).toBeVisible({ timeout: 3000 });

    // Rename inline
    const renamedTo = `${roleName}-renamed`;
    const input = page.locator(`input[value="${roleName}"]`).first();
    await input.fill(renamedTo);
    await input.press('Tab'); // blur -> saves
    await expect(page.locator(`input[value="${renamedTo}"]`)).toBeVisible({ timeout: 3000 });

    // Delete (handle confirm)
    page.once('dialog', (d) => d.accept());
    const deleteBtn = page.locator(`input[value="${renamedTo}"]`)
      .locator('..')
      .getByRole('button', { name: '✕' });
    await deleteBtn.click();
    await expect(page.locator(`input[value="${renamedTo}"]`)).toHaveCount(0, { timeout: 3000 });
  });

  test('bulk-check validity endpoint responds for empty selection', async ({ request, page, context }) => {
    // Get CSRF cookie that came with page load
    const cookies = await context.cookies();
    const csrf = cookies.find((c) => c.name === 'csrf_token')?.value || '';
    expect(csrf).toBeTruthy();

    const r = await request.post('/app/accounts/bulk-check-validity', {
      form: { account_ids: '' },
      headers: { 'X-CSRF-Token': csrf },
    });
    // Should return {results: []} for empty list
    expect(r.ok()).toBeTruthy();
    const body = await r.json();
    expect(body.results).toEqual([]);
  });

  test('catalog filters preserve state in URL', async ({ page }) => {
    await page.goto('/app/catalog/?search=test&sort=name&type_filter=channel');
    expect(page.url()).toContain('search=test');
    expect(page.url()).toContain('sort=name');
    // Selected options reflect URL
    await expect(page.locator('select[name="sort"]')).toHaveValue('name');
    await expect(page.locator('select[name="type_filter"]')).toHaveValue('channel');
  });
});
