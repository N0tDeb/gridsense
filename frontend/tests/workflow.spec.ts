import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('OpenDSS ready')).toBeVisible();
  await page.getByRole('button', { name: 'Incident analysis', exact: true }).click();
  await page.getByRole('button', { name: 'Restoration lab', exact: true }).click();
});

test('restoration, electrical comparison, replay, raw evidence, and review', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.getByRole('button', { name: 'Run restoration', exact: true }).click();
  await expect(
    page.getByRole('heading', {
      name: 'East backup · full section',
      exact: true,
    }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Nominal', exact: true }).click();
  await expect(
    page.getByRole('heading', {
      name: 'West backup · full section',
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.getByText(/Observed consequence: feed_b:/)).toBeVisible();
  await page.getByRole('button', { name: 'Decision evidence', exact: true }).click();
  await page.getByRole('button', { name: 'Show raw records' }).click();
  await expect(page.locator('.raw-records')).toContainText('measurement_at');
  await expect(page.locator('.raw-records')).toContainText('meter_b1');
  await page.getByRole('button', { name: 'Verify replay' }).click();
  await expect(page.getByText('Replay matched every recorded branch.')).toBeVisible();
  await page
    .getByLabel('Review note', { exact: true })
    .fill('Checked the stale west reading against the actual line loading.');
  await page.getByRole('button', { name: 'Question analysis' }).click();
  await expect(page.getByText('Analysis questioned', { exact: true })).toBeVisible();
  const download = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Export incident' }).click();
  expect((await download).suggestedFilename()).toMatch(/^gridsense-.*\.json$/);
  expect(errors).toEqual([]);
});

test('fixed-observation sweep produces real outcomes and export', async ({ page }) => {
  await page.getByRole('button', { name: 'Run restoration', exact: true }).click();
  await page.locator('.demand-sweep > summary').click();
  await expect(page.getByRole('button', { name: 'Run demand sweep' })).toBeEnabled();
  await page.getByRole('button', { name: 'Run demand sweep' }).click();
  await expect(page.getByRole('img', { name: /Maximum equipment loading/ })).toBeVisible();
  await page.getByText('Inspect all 27 simulated outcomes').click();
  await expect(page.locator('.sweep-body tbody tr')).toHaveCount(27);
  const download = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Export results Parquet' }).click();
  expect((await download).suggestedFilename()).toMatch(/\.parquet$/);
});

test('busy donors preserve critical service while leaving residential demand unserved', async ({
  page,
}) => {
  await page.getByRole('button', { name: 'High feeder demand', exact: true }).click();
  await page.getByRole('button', { name: 'Run restoration', exact: true }).click();
  await expect(page.getByRole('heading', { name: /backup · critical only/ })).toBeVisible();
  await expect(page.getByText('600 kW remains unserved')).toBeVisible();
  await expect(page.getByText('Out of service', { exact: true })).toBeVisible();
  await page.locator('.demand-sweep > summary').click();
  await expect(page.getByRole('button', { name: 'Run demand sweep' })).toBeDisabled();
});

test('archive preserves an incident across reload and makes it searchable', async ({ page }) => {
  const title = 'Browser archive retention case';
  await page.getByLabel('Incident title', { exact: true }).fill(title);
  await page.getByRole('button', { name: 'Run restoration', exact: true }).click();
  await expect(
    page.getByRole('heading', {
      name: 'East backup · full section',
      exact: true,
    }),
  ).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: 'Incident analysis', exact: true }).click();
  await page.getByRole('button', { name: /Incident archive/ }).click();
  await page.getByLabel('Search incidents').fill(title);
  await expect(page.locator('.archive-panel tbody tr')).toHaveCount(1);
  await page.getByRole('button', { name: `Open ${title}`, exact: true }).click();
  await expect(page.locator('.topology-panel .panel-header')).toContainText(title);
});

test('invalid fresh telemetry is explained and does not create a run', async ({ page }) => {
  await page.getByLabel('West reading age', { exact: true }).fill('0');
  await page.getByRole('button', { name: 'Run restoration', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Fresh telemetry must equal the actual load');
  await expect(
    page.getByText('Topology preview. Electrical readings appear after a simulation.'),
  ).toBeVisible();
});

test('mobile layout fits the viewport and can complete a restoration', async ({ page }) => {
  const diagram = page.getByTestId('topology');
  async function expectWholeDiagram() {
    await expect(diagram.locator('.react-flow__node')).toHaveCount(7);
    await expect
      .poll(() =>
        diagram.evaluate((canvas) => {
          const bounds = canvas.getBoundingClientRect();
          return [...canvas.querySelectorAll('.react-flow__node')].every((node) => {
            const r = node.getBoundingClientRect();
            return (
              r.width > 0 &&
              r.left >= bounds.left - 1 &&
              r.right <= bounds.right + 1 &&
              r.top >= bounds.top - 1 &&
              r.bottom <= bounds.bottom + 1
            );
          });
        }),
      )
      .toBe(true);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await expectWholeDiagram();
  await page.getByRole('button', { name: 'Run restoration', exact: true }).click();
  await expect(
    page.getByRole('heading', {
      name: 'East backup · full section',
      exact: true,
    }),
  ).toBeVisible();
  await expectWholeDiagram();
  await page.setViewportSize({ width: 1280, height: 720 });
  await expectWholeDiagram();
  await page.setViewportSize({ width: 390, height: 844 });
  await expectWholeDiagram();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth + 1,
  );
  expect(overflow).toBe(false);
  await page.getByRole('button', { name: 'Decision evidence', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'What the controller received' })).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1),
  ).toBe(false);
});
