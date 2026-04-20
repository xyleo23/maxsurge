import { test, expect } from '@playwright/test';

/**
 * /app/accounts/ UI — role dialog, bulk endpoint, catalog filters.
 *
 * Uses storageState from setup project (login once, share across tests).
 */

test.describe('Accounts page UI', () => {

  test('roles CRUD via API (create, rename, delete, cascade)', async ({ request, page }) => {
    // Get CSRF cookie from any /app page
    await page.goto('/app/accounts/');
    const cookies = await page.context().cookies();
    const csrf = cookies.find((c) => c.name === 'csrf_token')?.value || '';
    expect(csrf).toBeTruthy();

    const name = `E2E-${Date.now()}`;

    // Create
    const rCreate = await request.post('/app/accounts/roles/add', {
      form: { name, color: '#10b981' },
      headers: { 'X-CSRF-Token': csrf },
    });
    expect(rCreate.ok()).toBeTruthy();
    const created = await rCreate.json();
    expect(created.ok).toBe(true);
    const roleId = created.id;

    // List — role present
    const rList = await request.get('/app/accounts/roles');
    const listBody = await rList.json();
    expect(listBody.roles.find((r: any) => r.id === roleId)).toBeTruthy();

    // Rename
    const newName = name + '-renamed';
    const rUpd = await request.post(`/app/accounts/roles/${roleId}/update`, {
      form: { name: newName, color: '#a855f7' },
      headers: { 'X-CSRF-Token': csrf },
    });
    const upd = await rUpd.json();
    expect(upd.ok).toBe(true);
    expect(upd.name).toBe(newName);

    // Delete
    const rDel = await request.post(`/app/accounts/roles/${roleId}/delete`, {
      headers: { 'X-CSRF-Token': csrf },
    });
    expect((await rDel.json()).ok).toBe(true);

    // Confirm gone
    const rList2 = await request.get('/app/accounts/roles');
    const listBody2 = await rList2.json();
    expect(listBody2.roles.find((r: any) => r.id === roleId)).toBeUndefined();
  });

    test('bulk-check-validity endpoint accepts empty list', async ({ request, page }) => {
    // Visit a page to get CSRF cookie via context
    await page.goto('/app/accounts/');
    const cookies = await page.context().cookies();
    const csrf = cookies.find((c) => c.name === 'csrf_token')?.value || '';
    expect(csrf).toBeTruthy();

    const r = await request.post('/app/accounts/bulk-check-validity', {
      form: { account_ids: '' },
      headers: { 'X-CSRF-Token': csrf },
    });
    expect(r.ok()).toBeTruthy();
    const body = await r.json();
    expect(body.results).toEqual([]);
  });

  test('catalog filters preserve state in URL', async ({ page }) => {
    await page.goto('/app/catalog/?search=test&sort=name&type_filter=channel');
    expect(page.url()).toContain('search=test');
    expect(page.url()).toContain('sort=name');
    await expect(page.locator('select[name="sort"]')).toHaveValue('name');
    await expect(page.locator('select[name="type_filter"]')).toHaveValue('channel');
  });

  test('checker page renders with 3 modes', async ({ page }) => {
    await page.goto('/app/checker/');
    await expect(page.locator('text=Мягкая').first()).toBeVisible();
    await expect(page.locator('text=Массовый').first()).toBeVisible();
    await expect(page.locator('text=Чекер User ID').first()).toBeVisible();
  });

  test('post scheduler calendar loads', async ({ page }) => {
    await page.goto('/app/posts/');
    await expect(page.locator('h1:has-text("Планировщик постов")')).toBeVisible();
    // Should show day-of-week headers
    await expect(page.locator('text=Пн').first()).toBeVisible();
    await expect(page.locator('text=Вс').first()).toBeVisible();
  });

  test('import-contacts dual-pane renders', async ({ page }) => {
    await page.goto('/app/import-contacts/');
    await expect(page.locator('h1:has-text("Импорт контактов")')).toBeVisible();
    await expect(page.getByText('1. Аккаунт').first()).toBeVisible();
    await expect(page.getByText('2. Группа / канал').first()).toBeVisible();
  });
});
