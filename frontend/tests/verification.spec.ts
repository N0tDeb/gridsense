import { test, expect } from '@playwright/test';
import { readFile } from 'node:fs/promises';

test('all four controller tools are visible and usable on a narrow phone', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 740 });
  await page.goto('/');
  await page.getByRole('button', { name: 'Controller tests', exact: true }).click();
  const tools = page.getByRole('navigation', { name: 'Controller tools', exact: true });
  await expect(tools.getByRole('button')).toHaveCount(4);
  expect(
    await tools.evaluate((nav) =>
      [...nav.querySelectorAll('button')].every((button) => {
        const r = button.getBoundingClientRect();
        return r.left >= 0 && r.right <= innerWidth;
      }),
    ),
  ).toBe(true);
  for (const [tool, heading] of [
    ['Controller comparison', 'Controller comparison'],
    ['Switch confirmation', 'Switch position and confirmation'],
    ['IEEE feeder check', 'Published voltage reference'],
    ['Failure search', 'Search for an avoidable violation'],
  ]) {
    await tools.getByRole('button', { name: tool, exact: true }).click();
    await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible();
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)).toBe(
    false,
  );
});

test('controller regression preserves service, rejects hold, exports and reopens evidence', async ({
  page,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('/');
  await page.getByRole('button', { name: 'Controller tests', exact: true }).click();
  await page.getByRole('button', { name: 'Compare controllers', exact: true }).click();
  const result = page.getByTestId('regression-result');
  await expect(
    result.getByRole('heading', {
      name: 'Requirements met · no service regression',
    }),
  ).toBeVisible();
  await expect(result.getByText('tie_b', { exact: true })).toBeVisible();
  await expect(result.getByText('tie_c', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Verify recorded run', exact: true }).click();
  await expect(
    page.getByText('Replay matched the recorded run within numerical tolerance.'),
  ).toBeVisible();
  const downloaded = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Export complete run' }).click();
  const download = await downloaded;
  const payload = JSON.parse(await readFile((await download.path())!, 'utf8'));
  expect(payload.accepted).toBe(true);
  expect(payload.baseline.electrical_pass).toBe(false);
  expect(payload.content_sha256).toHaveLength(64);
  await page
    .getByRole('combobox', { name: 'Candidate controller', exact: true })
    .selectOption('hold-v1');
  await page
    .getByRole('button', {
      name: 'Compare with saved baseline',
    })
    .click();
  await expect(result.getByRole('heading', { name: 'Change needs review' })).toBeVisible();
  await expect(result.getByText('Lower restored_kw', { exact: true })).toBeVisible();
  await expect(result.getByText(/Compared with recorded outcome/)).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: 'Controller tests', exact: true }).click();
  await page
    .getByRole('button', {
      name: `Open verification ${payload.id}`,
      exact: true,
    })
    .click();
  await expect(
    result.getByRole('heading', {
      name: 'Requirements met · no service regression',
    }),
  ).toBeVisible();
  await page
    .getByText('Scenario JSON and service requirements', {
      exact: true,
    })
    .click();
  await page
    .getByRole('textbox', { name: 'Scenario JSON', exact: true })
    .fill(JSON.stringify({ ...payload.request.case, title: { invalid: true } }));
  await page.getByRole('button', { name: 'Compare controllers', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Input should be a valid string');
  expect(errors).toEqual([]);
});

test('published feeder reference and modified-feeder restoration are distinct real runs', async ({
  page,
}) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Controller tests', exact: true }).click();
  await page.getByRole('button', { name: 'IEEE feeder check', exact: true }).click();
  await page.getByRole('button', { name: 'Validate IEEE feeder', exact: true }).click();
  await expect(page.getByText('Reference check passed', { exact: true })).toBeVisible();
  await expect(
    page.getByRole('heading', {
      name: 'Published voltage reference',
      exact: true,
    }),
  ).toBeVisible();
  const scope = page.getByText(/This checks voltages only/);
  await expect(scope).toContainText('native-default extended audit passes 52 of 56 checks');
  await expect(scope).toContainText('separately configured constant-PQ reference passes 56 of 56');
  await expect(scope).toContainText('ASSURANCE.md records each configuration and its scope');
  await expect(page.getByRole('cell', { name: '675.3', exact: true })).toBeVisible();
  await expect(
    page.getByRole('row').filter({ has: page.getByRole('cell', { name: '692.3', exact: true }) }),
  ).toContainText('0.9778');
  await page.getByRole('button', { name: 'Controller comparison', exact: true }).click();
  await page.getByRole('combobox', { name: 'Test scenario', exact: true }).selectOption('2');
  await page.getByRole('button', { name: 'Compare controllers', exact: true }).click();
  await expect(
    page
      .getByTestId('regression-result')
      .getByRole('heading', { name: 'Requirements met · no service regression' }),
  ).toBeVisible();
  await expect(page.getByRole('cell', { name: 'backup_rg', exact: true }).first()).toBeVisible();
});

test('mobile event search shows commanded, physical and confirmed states and can replay', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByRole('button', { name: 'Controller tests', exact: true }).click();
  await page.getByRole('button', { name: 'Switch confirmation', exact: true }).click();
  await page.getByRole('spinbutton', { name: 'Event sequences to test', exact: true }).fill('4');
  await page.getByRole('button', { name: 'Search switch failures', exact: true }).click();
  const result = page.getByTestId('temporal-result');
  await expect(
    result.getByRole('heading', { name: 'False restoration claim reproduced' }),
  ).toBeVisible();
  await expect(
    page.getByTestId('deadline-summary').getByText('0 kW · switch open', { exact: true }),
  ).toBeVisible();
  await expect(result.getByText('Actuator remained open', { exact: true })).toBeVisible();
  await expect(result.getByRole('cell', { name: /^unknown — confirmation timeout/ })).toBeVisible();
  await expect(result.getByText(/delay_confirmation \(5s\)/)).toBeVisible();
  await page.getByRole('button', { name: 'Verify recorded run', exact: true }).click();
  await expect(
    page.getByText('Replay matched the recorded run within numerical tolerance.'),
  ).toBeVisible();
  const fits = await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1);
  expect(fits).toBe(true);
});

test('a live incident can become a portable regression case without changing its record', async ({
  page,
}) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Incident analysis', exact: true }).click();
  await page.getByRole('button', { name: 'Restoration lab', exact: true }).click();
  await page.getByRole('button', { name: 'Run restoration', exact: true }).click();
  await expect(page.locator('.decision-summary')).toBeVisible();
  await page.getByRole('button', { name: 'Decision evidence', exact: true }).click();
  await page.getByRole('button', { name: 'Test controller changes', exact: true }).click();
  await page
    .getByText('Scenario JSON and service requirements', {
      exact: true,
    })
    .click();
  await expect(page.getByRole('textbox', { name: 'Scenario JSON', exact: true })).toHaveValue(
    /Imported inputs/,
  );
  await page.getByRole('button', { name: 'Compare controllers', exact: true }).click();
  await expect(page.getByTestId('regression-result')).toBeVisible();
});

test('late preset loading preserves the incident selected for regression', async ({ page }) => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route('**/api/verification/presets', async (route) => {
    const response = await route.fetch();
    await gate;
    await route.fulfill({ response });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Incident analysis', exact: true }).click();
  await page.getByRole('button', { name: 'Restoration lab', exact: true }).click();
  await page.getByRole('button', { name: 'Run restoration', exact: true }).click();
  await expect(page.locator('.decision-summary')).toBeVisible();
  await page.getByRole('button', { name: 'Decision evidence', exact: true }).click();
  await page.getByRole('button', { name: 'Test controller changes', exact: true }).click();
  await page
    .getByText('Scenario JSON and service requirements', {
      exact: true,
    })
    .click();
  const editor = page.getByRole('textbox', {
    name: 'Scenario JSON',
    exact: true,
  });
  try {
    await expect(editor).toHaveValue(/Imported inputs/);
  } finally {
    release();
  }
  await expect(
    page.getByRole('combobox', { name: 'Test scenario', exact: true }).locator('option'),
  ).toHaveCount(4);
  await expect(editor).toHaveValue(/Imported inputs/);
});

test('opening a saved temporal run restores its actual input settings', async ({
  page,
  request,
}) => {
  const response = await request.post('/api/verification/temporal', {
    data: { seed: 123, budget: 1, timeout_s: 3 },
  });
  expect(response.status()).toBe(201);
  const record = await response.json();
  await page.goto('/');
  await page.getByRole('button', { name: 'Controller tests', exact: true }).click();
  await page
    .getByRole('button', {
      name: `Open verification ${record.id}`,
      exact: true,
    })
    .click();
  await expect(page.getByRole('spinbutton', { name: 'Search seed', exact: true })).toHaveValue(
    '123',
  );
  await expect(
    page.getByRole('spinbutton', { name: 'Event sequences to test', exact: true }),
  ).toHaveValue('1');
  await expect(
    page.getByRole('spinbutton', {
      name: 'Confirmation timeout (s)',
      exact: true,
    }),
  ).toHaveValue('3');
  await expect(page.getByTestId('temporal-result')).toBeVisible();
});
