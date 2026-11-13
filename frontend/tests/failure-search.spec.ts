import { readFile } from 'node:fs/promises';
import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('OpenDSS ready')).toBeVisible();
  await page.getByRole('button', { name: 'Controller tests', exact: true }).click();
  await page.getByRole('button', { name: 'Failure search', exact: true }).click();
});

test('discover, reduce, reproduce, export, and reopen a failure in the electrical lab', async ({
  page,
}) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.getByLabel('Simplification checks', { exact: true }).fill('24');
  const response = page.waitForResponse(
    (r) => r.url().endsWith('/api/failure-searches') && r.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Compare searches', exact: true }).click();
  await expect(
    page.getByRole('heading', {
      name: 'Avoidable violation found',
      exact: true,
    }),
  ).toBeVisible({ timeout: 90_000 });
  const record = await (await response).json();
  expect(record.reduced_finding.truth_inside_assumed_range).toBe(true);
  expect(record.reduced_finding.actual_loading_pct).toBeGreaterThan(100);
  expect(record.reduced_finding.feasible_alternative.feasible).toBe(true);
  expect(record.reduction.reduced_complexity[1]).toBeLessThan(
    record.reduction.original_complexity[1],
  );
  await expect(page.getByRole('table', { name: 'Failure simplification' })).toBeVisible();
  await page.getByRole('button', { name: 'Replay failure cases', exact: true }).click();
  await expect(
    page.getByText('Original and reduced failures reproduced.', {
      exact: true,
    }),
  ).toBeVisible();
  const download = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Export search JSON', exact: true }).click();
  const exported = await download;
  expect(exported.suggestedFilename()).toBe(`gridsense-failure-${record.id}.json`);
  expect(JSON.parse(await readFile((await exported.path())!, 'utf8'))).toEqual(record);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page
      .getByRole('table', { name: 'Failure simplification' })
      .evaluate(
        (table) => table.parentElement!.scrollWidth <= table.parentElement!.clientWidth + 1,
      ),
  ).toBe(true);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole('button', { name: 'Open simplified incident', exact: true }).click();
  await expect(page.locator('.topology-panel .panel-header')).toContainText(
    'Discovered restoration case',
  );
  await expect(page.getByText(/Observed consequence: feed_b:/)).toBeVisible();
  await page.getByRole('button', { name: 'Decision evidence', exact: true }).click();
  await page.getByRole('button', { name: 'Show raw records', exact: true }).click();
  await expect(page.locator('.raw-records')).toContainText('meter_b1');
  await page.reload();
  await page.getByRole('button', { name: 'Controller tests', exact: true }).click();
  await page.getByRole('button', { name: 'Failure search', exact: true }).click();
  await page
    .getByRole('button', {
      name: `Open search ${record.id.slice(0, 8)}`,
      exact: true,
    })
    .click();
  await expect(
    page.getByRole('heading', {
      name: 'Avoidable violation found',
      exact: true,
    }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test('mobile search handles an exhausted non-failing domain without claiming safety', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page
    .getByRole('combobox', { name: 'Controller under test', exact: true })
    .selectOption('guarded');
  await page.getByLabel('Trials per method', { exact: true }).fill('4');
  await page.getByText('Demand bounds and simplification reference', { exact: true }).click();
  for (const [label, value] of [
    ['Affected demand', '1'],
    ['Actual west demand', '.8'],
    ['Actual east demand', '1'],
    ['Reported west demand', '.8'],
  ]) {
    for (const field of ['minimum', 'maximum', 'reference'])
      await page.getByLabel(`${label} ${field}`, { exact: true }).fill(value);
  }
  await page.getByRole('button', { name: 'Compare searches', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'No target failure found', exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText(/No failure was found within this search. That does not establish safety/),
  ).toBeVisible();
  await expect(page.getByRole('button', { name: 'Replay failure cases', exact: true })).toHaveCount(
    0,
  );
  await page.getByText('Outcome categories and search trace', { exact: true }).click();
  await expect(page.getByText(/All admissible grid points evaluated/)).toHaveCount(2);
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1),
  ).toBe(false);
});

test('server explains an inconsistent search reference without saving a run', async ({ page }) => {
  await page.getByText('Demand bounds and simplification reference', { exact: true }).click();
  await page.getByLabel('Actual west demand reference', { exact: true }).fill('2');
  await page.getByRole('button', { name: 'Compare searches', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText(
    'Reference west demand must be inside the assumed uncertainty range',
  );
  await expect(
    page.getByRole('heading', {
      name: 'Find and simplify a failing case',
      exact: true,
    }),
  ).toBeVisible();
});
