import { test, expect } from '@playwright/test';

test('readiness changes after startup without advancing the live session', async ({ page }) => {
  let broken = false;
  await page.route('**/api/health', async (route) => {
    if (!broken) return route.continue();
    return route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'unavailable',
        workers: 0,
        detail: 'Simulation worker unavailable. Restart the local server.',
      }),
    });
  });
  await page.goto('/');
  const indicator = page.locator('.engine-status');
  await expect(indicator).toHaveText('OpenDSS ready');
  await page.getByLabel('Restoration policy', { exact: true }).selectOption('off');
  await page.getByLabel('Session duration (s)', { exact: true }).fill('3');
  const created = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/sessions') && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Create live session', exact: true }).click();
  const id = (await (await created).json()).id;
  const original = await (await page.request.get(`/api/sessions/${id}/export`)).json();
  broken = true;
  await expect(indicator).toHaveText('Engine unavailable', { timeout: 10_000 });
  await expect(indicator).toHaveAttribute('title', /Restart the local server/);
  broken = false;
  await expect(indicator).toHaveText('OpenDSS ready', { timeout: 10_000 });
  await expect(page.getByTestId('live-clock')).toHaveText('t=0 s');
  const after = await (await page.request.get(`/api/sessions/${id}/export`)).json();
  expect(after.frames).toEqual(original.frames);
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)).toBe(
    false,
  );
});

test('an unavailable startup is reported instead of staying at connecting', async ({ page }) => {
  await page.route('**/api/health', (route) =>
    route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'unavailable',
        workers: 0,
        detail: 'Simulation worker unavailable. Restart the local server.',
      }),
    }),
  );
  await page.goto('/');
  await expect(page.locator('.engine-status')).toHaveText('Engine unavailable');
  await expect(page.getByText(/Cannot connect to GridSense/)).toBeVisible();
  await expect(page.getByText('Connecting to engine', { exact: true })).toHaveCount(0);
});
