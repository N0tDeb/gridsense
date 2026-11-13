import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';
import { readFile } from 'node:fs/promises';

test('mobile group view keeps native readings current and inspection does not advance time', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const id = await create(page, 'off', 4);
  const view = page.getByLabel('Diagram view', { exact: true });
  const canvas = page.getByTestId('live-topology');
  const group = canvas.locator('.react-flow__node[data-id="a1"]');
  await view.selectOption('a1');
  await expect.poll(async () => (await group.boundingBox())?.width ?? 0).toBeGreaterThan(220);
  expect(
    await canvas.evaluate((root) => {
      const controls = root.querySelector('.react-flow__controls')!.getBoundingClientRect();
      return [
        ...root.querySelectorAll(
          '.react-flow__node[data-id="a1"] span, .react-flow__node[data-id="a1"] strong',
        ),
      ]
        .filter((label) => {
          const range = document.createRange();
          range.selectNodeContents(label);
          const r = range.getBoundingClientRect();
          return (
            r.left < controls.right &&
            r.right > controls.left &&
            r.top < controls.bottom &&
            r.bottom > controls.top
          );
        })
        .map((label) => label.textContent);
    }),
  ).toEqual([]);
  const loadButton = canvas.getByRole('button', { name: 'Inspect load:a1', exact: true });
  await loadButton.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByLabel('Inspect equipment', { exact: true })).toHaveValue('load:a1');
  await closePanel(page);
  await expect(loadButton).toBeFocused();
  expect((await record(page, id)).frames).toHaveLength(1);
  await openScenario(page);
  await page.getByLabel('Disturbance type', { exact: true }).selectOption('demand');
  await page.getByLabel('Demand feeder', { exact: true }).selectOption('a');
  await page.getByLabel('Demand multiplier (×)', { exact: true }).fill('1.2');
  await schedule(page);
  await step(page, 1);
  await expect(view).toHaveValue('a1');
  await expect.poll(async () => (await group.boundingBox())?.width ?? 0).toBeGreaterThan(220);
  const live = await (await page.request.get(`/api/sessions/${id}/simulation`)).json();
  const load = live.simulation.electrical.load_measurements.find(
    (row: { load_id: string }) => row.load_id === 'a1',
  );
  expect(load.requested_kw).toBe(480);
  await expect(loadButton).toContainText(
    `${load.served_kw.toLocaleString('en-US', { maximumFractionDigits: 0 })} kW`,
  );
  await canvas.getByRole('button', { name: 'Show whole grid', exact: true }).click();
  await expect(view).toHaveValue('');
  await expect
    .poll(() =>
      canvas.evaluate((root) => {
        const bounds = root.getBoundingClientRect();
        return [...root.querySelectorAll('.react-flow__node')].every((node) => {
          const r = node.getBoundingClientRect();
          return (
            r.left >= bounds.left - 1 &&
            r.right <= bounds.right + 1 &&
            r.top >= bounds.top - 1 &&
            r.bottom <= bounds.bottom + 1
          );
        });
      }),
    )
    .toBe(true);
  await expect(page.getByTestId('live-clock')).toHaveText('t=1 s');
  expect((await record(page, id)).frames).toHaveLength(2);
});

async function checkTopology(page: Page) {
  const canvas = page.getByTestId('live-topology');
  await expect(canvas.locator('.react-flow__edge-path')).toHaveCount(8);
  await expect(canvas.locator('.react-flow__edge-textwrapper')).toHaveCount(8);
  await expect
    .poll(() =>
      canvas.evaluate((root) => {
        const nodes = [...root.querySelectorAll('.react-flow__node')].map((node) =>
          node.getBoundingClientRect(),
        );
        return [...root.querySelectorAll('.react-flow__edge-textwrapper')]
          .filter((label) => {
            const rect = label.getBoundingClientRect();
            return nodes.some(
              (node) =>
                rect.left < node.right - 1 &&
                rect.right > node.left + 1 &&
                rect.top < node.bottom - 1 &&
                rect.bottom > node.top + 1,
            );
          })
          .map((label) => label.textContent);
      }),
    )
    .toEqual([]);
}

async function create(page: Page, policy = 'nominal', horizon = 12) {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Live Grid', exact: true })).toBeVisible();
  await page.getByLabel('Restoration policy', { exact: true }).selectOption(policy);
  await page.getByLabel('Session duration (s)', { exact: true }).fill(String(horizon));
  const response = page.waitForResponse(
    (r) => r.url().endsWith('/api/sessions') && r.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Create live session', exact: true }).click();
  const result = await response;
  expect(result.status()).toBe(201);
  const receipt = await result.json();
  await expect(page.getByTestId('live-clock')).toHaveText('t=0 s');
  await expect(page.getByRole('button', { name: 'Step one second' })).toBeEnabled();
  await checkTopology(page);
  return receipt.id as string;
}
async function step(page: Page, at: number) {
  await page.getByRole('button', { name: 'Step one second' }).click();
  await expect(page.getByTestId('live-clock')).toHaveText(`t=${at} s`);
  await expect(page.getByText('Waiting for the backend to commit.', { exact: false })).toHaveCount(
    0,
  );
  await checkTopology(page);
}
async function openScenario(page: Page) {
  const dialog = page.getByRole('dialog', { name: 'Add disturbance', exact: true });
  if (!(await dialog.isVisible()))
    await page.getByRole('button', { name: 'Add disturbance', exact: true }).click();
  await expect(dialog).toBeVisible();
}
async function closePanel(page: Page) {
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
}
async function openEquipment(page: Page, asset?: string) {
  await page.getByRole('button', { name: 'Inspect equipment', exact: true }).click();
  await expect(
    page.getByRole('dialog', { name: 'Equipment inspection', exact: true }),
  ).toBeVisible();
  if (asset) await page.getByLabel('Inspect equipment', { exact: true }).selectOption(asset);
}
async function openAlarms(page: Page) {
  await page.getByRole('button', { name: 'View alarms', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'Incident details', exact: true })).toBeVisible();
}
async function schedule(page: Page) {
  await openScenario(page);
  const response = page.waitForResponse(
    (r) => r.url().includes('/actions') && r.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Schedule disturbance', exact: true }).click();
  expect((await response).status()).toBe(200);
  await expect(
    page.getByRole('dialog', { name: 'Add disturbance', exact: true }),
  ).not.toBeVisible();
  await expect(page.getByRole('button', { name: 'Step one second' })).toBeEnabled();
}
async function record(page: Page, id: string) {
  const response = await page.request.get(`/api/sessions/${id}/export`);
  expect(response.ok()).toBe(true);
  return response.json();
}

test('healthy feeder, isolation, confirmed backup, repair, recovery, raw evidence and replay', async ({
  page,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const id = await create(page);
  await expect(page.getByTestId('live-supply')).toContainText('Normal supply verified');
  await expect(page.getByTestId('live-unserved')).toContainText('0 kW');
  await schedule(page);
  await step(page, 1);
  await expect(page.getByTestId('live-unserved')).toContainText('1,000 kW');
  await expect(page.getByTestId('live-supply')).toContainText('Waiting for switch confirmation');
  await openAlarms(page);
  const alarm = page.locator('.live-alarm').filter({
    has: page.locator('summary strong', { hasText: 'equipment unavailable · line:feed_a' }),
  });
  await alarm.locator(':scope > summary').click();
  await expect(alarm.getByRole('table')).toContainText('line:feed_a/available');
  await expect(alarm.getByRole('table')).toContainText('false');
  await alarm.getByText('Raw alert record', { exact: true }).click();
  await expect(alarm.locator('pre')).toContainText('trigger_rows');
  await closePanel(page);
  await step(page, 2);
  await expect(page.getByTestId('live-supply')).toContainText('Alternate supply verified');
  await expect(page.locator('.live-incident')).toContainText('line:feed_a');
  await page.getByRole('button', { name: 'Switch commands', exact: true }).click();
  await expect(page.getByRole('table', { name: 'Switch commands', exact: true })).toContainText(
    'confirmed',
  );
  await closePanel(page);
  await page.getByRole('button', { name: 'Schedule repair for feed_a', exact: true }).click();
  await step(page, 3);
  let run = await record(page, id);
  expect(run.frames[3].physical.equipment_outages).toEqual([]);
  expect(run.frames[3].physical.closed_lines).not.toContain('feed_a');
  expect(run.frames[3].control.commands['command-2'].issued_at_s).toBe(3);
  await step(page, 4);
  await expect(page.getByTestId('live-supply')).toContainText('Waiting for switch confirmation');
  await expect(page.getByTestId('live-unserved')).toContainText('1,000 kW');
  await step(page, 5);
  await expect(page.getByTestId('live-supply')).toContainText('Normal supply verified');
  await step(page, 6);
  await expect(page.getByTestId('live-supply')).toContainText('Normal supply verified');
  await page.getByRole('button', { name: 'View incident timeline' }).click();
  await expect(page.getByRole('table', { name: 'Live incident timeline' })).toBeVisible();
  await page.getByRole('button', { name: 'Inspect tick 1', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Recorded tick 1 s' })).toBeVisible();
  await page
    .getByTestId('live-analysis')
    .getByText(/Compare \d+ evaluated alternatives/)
    .click();
  await expect(page.getByRole('table', { name: 'Live restoration alternatives' })).toContainText(
    'Close line:tie_c',
  );
  await page.getByRole('button', { name: 'Check session replay', exact: true }).click();
  await expect(
    page.getByText(/Strict replay matched · server session through t=6 s/),
  ).toBeVisible();
  const downloaded = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export captured session', exact: true }).click();
  run = JSON.parse(await readFile((await (await downloaded).path())!, 'utf8'));
  expect(run.id).toBe(id);
  expect(run.frames.at(-1).metrics.position_changes).toBe(3);
  expect(run.frames.at(-1).metrics.unserved_kwh).toBeCloseTo(2000 / 3600, 6);
  expect(errors).toEqual([]);
});

test('transformer repair restores availability without claiming LV supply when control is off', async ({
  page,
}) => {
  const id = await create(page, 'off');
  await openScenario(page);
  await page.getByLabel('Equipment', { exact: true }).selectOption('transformer:tx_a1');
  await schedule(page);
  await step(page, 1);
  await expect(page.getByTestId('live-unserved')).toContainText('400 kW');
  const topology = page.getByTestId('live-topology');
  await expect(
    topology.getByRole('button', { name: 'Inspect transformer:tx_a1', exact: true }),
  ).toContainText('Unavailable · isolated');
  await expect(topology.getByRole('button', { name: 'Inspect bus:a1', exact: true })).toContainText(
    'pu',
  );
  await page.getByRole('button', { name: 'Schedule repair for tx_a1' }).click();
  await step(page, 2);
  await expect(
    topology.getByRole('button', { name: 'Inspect transformer:tx_a1', exact: true }),
  ).toContainText('Open');
  const run = await record(page, id);
  expect(run.frames.at(-1).physical.equipment_outages).toEqual([]);
  expect(run.frames.at(-1).electrical.unserved_kw).toBeCloseTo(400, 4);
  expect(run.frames.at(-1).control.commands).toEqual({});
});

test('guarded restoration exposes partial service and finite prediction samples', async ({
  page,
}) => {
  test.setTimeout(90_000);
  const id = await create(page, 'guarded');
  await schedule(page);
  for (let at = 1; at <= 3; at++) await step(page, at);
  await expect(page.getByTestId('live-supply')).toContainText('Partial supply verified');
  await expect(page.getByTestId('live-unserved')).toContainText('250 kW');
  const run = await record(page, id);
  expect(run.frames[3].electrical.critical_served_kw).toBeCloseTo(400, 4);
  expect(run.frames[3].physical.open_transformers).toEqual(['tx_b2']);
  expect(run.frames[1].control.last_plan.uncertainty_samples).toHaveLength(15);
  expect(
    run.frames.every((f: { electrical: { feasible: boolean } }) => f.electrical.feasible),
  ).toBe(true);
});

test('a stale-demand overload shows its received value and avoids reopening the unsafe load set', async ({
  page,
}) => {
  const id = await create(page);
  await schedule(page);
  await openScenario(page);
  await page.getByLabel('Disturbance type', { exact: true }).selectOption('demand');
  await page.getByLabel('Demand feeder', { exact: true }).selectOption('c');
  await page.getByLabel('Demand multiplier (×)', { exact: true }).fill('2');
  await schedule(page);
  for (const asset of ['load:c1', 'load:c2']) {
    await openScenario(page);
    await page.getByLabel('Disturbance type', { exact: true }).selectOption('transport');
    await page.getByLabel('Equipment', { exact: true }).selectOption(asset);
    await page.getByLabel('Drop new measurements', { exact: true }).check();
    await schedule(page);
  }
  await step(page, 1);
  await step(page, 2);
  const run = await record(page, id);
  const overload = run.frames[2].control.last_plan.measured_overloads.find(
    (row: { equipment: string }) => row.equipment === 'line:feed_c',
  );
  expect(overload.row.value).toBeGreaterThan(100);
  await page.getByRole('button', { name: 'Restoration decision', exact: true }).click();
  const plan = page.getByTestId('live-plan');
  await expect(plan).toContainText(`line:feed_c at ${overload.row.value.toFixed(1)}%`);
  await expect(plan).toContainText('measured at 2 s; limit 100%');
  await closePanel(page);
  for (let at = 3; at <= 5; at++) await step(page, at);
  const corrected = await record(page, id);
  expect(corrected.frames[5].electrical.feasible).toBe(true);
  expect(corrected.frames[5].electrical.unserved_kw).toBeCloseTo(1000, 4);
  expect(corrected.frames[5].control.unsafe_exposures.length).toBeGreaterThan(0);
  await page.getByRole('button', { name: 'Restoration decision', exact: true }).click();
  await plan.locator('summary').filter({ hasText: 'evaluated alternatives' }).click();
  await expect(plan).toContainText('Unrelated switching cannot clear this check');
  const replay = await (await page.request.post(`/api/sessions/${id}/replay`)).json();
  expect(replay.matched).toBe(true);
  expect(replay.differences).toEqual([]);
  await expect(page.getByTestId('live-clock')).toHaveText('t=5 s');
});

test('saved plans without timing metadata remain readable without invented values', async ({
  page,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.route('**/api/sessions/*/simulation', async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    const plan = body.control?.last_plan;
    if (plan) {
      for (const key of ['timing', 'energy_horizon_s', 'measured_overloads', 'unsafe_exposures'])
        delete plan[key];
      for (const candidate of [...plan.candidates, plan.selected].filter(Boolean)) {
        delete candidate.energy;
        delete candidate.completion_offset_s;
      }
    }
    await route.fulfill({ response, json: body });
  });
  const id = await create(page);
  await schedule(page);
  await step(page, 1);
  await page.getByRole('button', { name: 'Restoration decision', exact: true }).click();
  const plan = page.getByTestId('live-plan');
  await expect(plan).toContainText(
    'Switching times and predicted energy were not recorded for this plan',
  );
  await expect(page.getByTestId('planning-energy')).toHaveCount(0);
  await plan.locator('summary').filter({ hasText: 'evaluated alternatives' }).click();
  await expect(plan.getByRole('table')).toContainText('Not recorded');
  expect((await record(page, id)).frames).toHaveLength(2);
  expect(errors).toEqual([]);
});

test('public planning times and predicted energy are recorded separately from actual switching', async ({
  page,
}) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Live Grid', exact: true })).toBeVisible();
  await page.getByText('Planning assumptions', { exact: true }).click();
  await page.getByLabel('Estimated switching time (s)', { exact: true }).fill('2');
  await page.getByLabel('Estimated confirmation delay (s)', { exact: true }).fill('1');
  await page.getByLabel('Energy comparison window (s)', { exact: true }).fill('8');
  const created = page.waitForResponse(
    (r) => r.url().endsWith('/api/sessions') && r.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Create live session', exact: true }).click();
  const result = await created;
  expect(result.status()).toBe(201);
  const receipt = await result.json();
  await expect(page.getByTestId('live-clock')).toHaveText('t=0 s');
  await schedule(page);
  await step(page, 1);
  const run = await record(page, receipt.id);
  expect(run.definition.control.planning_timing).toEqual({
    actuation_delay_s: 2,
    confirmation_delay_s: 1,
    energy_horizon_s: 8,
  });
  const plan = run.frames[1].control.last_plan;
  expect(plan.timing).toEqual(run.definition.control.planning_timing);
  expect(plan.selected.energy.horizon_s).toBe(8);
  expect(plan.selected.energy.unserved_kwh).toBeCloseTo(2000 / 3600, 5);
  await page.getByRole('button', { name: 'Restoration decision', exact: true }).click();
  await expect(page.getByTestId('planning-timing')).toContainText('2 s to switch');
  await expect(page.getByTestId('planning-timing')).toContainText('next 8 s');
  await expect(page.getByTestId('planning-energy')).toContainText('0.5556 kWh');
  await closePanel(page);
  await step(page, 2);
  const actual = await record(page, receipt.id);
  expect(actual.frames[2].control.commands['command-1'].measured_at_s).toBe(2);
  expect(actual.frames[1].control.last_plan.selected.completion_offset_s).toBe(3);
});

test('native overload alarms retain two triggering rows and clear only after healthy samples', async ({
  page,
}) => {
  const id = await create(page, 'off');
  await openScenario(page);
  await page.getByLabel('Disturbance type', { exact: true }).selectOption('demand');
  await openScenario(page);
  await page.getByLabel('Demand multiplier (×)', { exact: true }).fill('2');
  await schedule(page);
  await step(page, 1);
  await step(page, 2);
  const run = await record(page, id);
  const alarm = run.frames[2].observation.alarms.find(
    (a: { rule: string; equipment: string }) =>
      a.rule === 'overload' && a.equipment === 'transformer:tx_a1',
  );
  expect(alarm.trigger_rows).toHaveLength(2);
  expect(
    alarm.trigger_rows.every(
      (r: { value: number; source: string }) => r.value > 100 && r.source === 'OpenDSS',
    ),
  ).toBe(true);
  await openAlarms(page);
  const card = page
    .locator('.live-alarm')
    .filter({ has: page.locator('summary strong', { hasText: 'overload · transformer:tx_a1' }) });
  await card.locator(':scope > summary').click();
  await expect(card.getByRole('table')).toContainText('loading_pct');
  await closePanel(page);
  await openScenario(page);
  await page.getByLabel('Demand multiplier (×)', { exact: true }).fill('1');
  await schedule(page);
  await step(page, 3);
  await step(page, 4);
  await openAlarms(page);
  await expect(card.locator(':scope > summary')).toContainText('Active since');
  await closePanel(page);
  await step(page, 5);
  await openAlarms(page);
  await expect(card.locator(':scope > summary')).toContainText('Cleared at 5 s');
});

test('lost command confirmation stays unknown even when native alternate supply returns', async ({
  page,
}) => {
  const id = await create(page);
  await openScenario(page);
  await page.getByLabel('Disturbance type', { exact: true }).selectOption('actuator');
  await openScenario(page);
  await page.getByLabel('Equipment', { exact: true }).selectOption('line:tie_c');
  await page.getByLabel('Drop command confirmation', { exact: true }).check();
  await schedule(page);
  await openScenario(page);
  await page.getByLabel('Disturbance type', { exact: true }).selectOption('outage');
  await openScenario(page);
  await page.getByLabel('Equipment', { exact: true }).selectOption('line:feed_a');
  await schedule(page);
  for (let at = 1; at <= 7; at++) await step(page, at);
  await expect(page.getByTestId('live-supply')).toContainText('Alternate supply verified');
  await expect(page.getByTestId('live-supply')).toContainText('Switch confirmation unknown');
  await page.getByRole('button', { name: 'Switch commands', exact: true }).click();
  await expect(page.getByRole('table', { name: 'Switch commands', exact: true })).toContainText(
    'unknown',
  );
  const run = await record(page, id);
  expect(run.frames.at(-1).control.status).toBe('confirmation_unknown');
  expect(run.frames.at(-1).control.commands['command-1'].status).toBe('unknown');
  expect(Object.keys(run.frames.at(-1).control.commands)).toHaveLength(1);
  expect(run.frames.at(-1).physical.closed_lines).toContain('tie_c');
});

test('dropped telemetry becomes stale and restores only on a new delivered sample', async ({
  page,
}) => {
  await create(page);
  await openScenario(page);
  await page.getByLabel('Disturbance type', { exact: true }).selectOption('transport');
  await openScenario(page);
  await page.getByLabel('Equipment', { exact: true }).selectOption('line:feed_c');
  await page.getByLabel('Drop new measurements', { exact: true }).check();
  await schedule(page);
  for (let at = 1; at <= 3; at++) await step(page, at);
  await openEquipment(page, 'line:feed_c');
  await expect(
    page.getByRole('table', { name: 'Received measurements', exact: true }),
  ).toContainText('Stale');
  await closePanel(page);
  await expect(page.getByTestId('live-supply')).toContainText('Awaiting valid measurements');
  await expect(page.getByText(/Received measurements: \d+ stale/)).toBeVisible();
  await openScenario(page);
  await page.getByLabel('Drop new measurements', { exact: true }).uncheck();
  await schedule(page);
  await step(page, 4);
  await expect(page.getByTestId('live-supply')).toContainText('Normal supply verified');
  await openEquipment(page, 'line:feed_c');
  await expect(
    page.getByRole('table', { name: 'Received measurements', exact: true }),
  ).not.toContainText('Stale');
  await closePanel(page);
});

test('paced playback stops at the backend horizon and reload reopens the same committed session', async ({
  page,
}) => {
  const id = await create(page, 'off', 3);
  await page.getByLabel('Playback speed', { exact: true }).selectOption('10');
  await page.getByRole('button', { name: 'Play session', exact: true }).click();
  await expect(page.getByTestId('live-clock')).toHaveText('t=3 s');
  await expect(page.getByRole('button', { name: 'Step one second' })).toBeDisabled();
  await page.reload();
  await expect(page.getByTestId('live-clock')).toHaveText('t=3 s');
  expect((await record(page, id)).frames).toHaveLength(4);
  await expect(page.getByLabel('Saved live session')).toHaveValue(id);
});

test('a concurrent revision rejects the old action, refreshes, and never advances a hidden tick', async ({
  page,
}) => {
  const id = await create(page);
  let injected = false;
  await page.route(`**/api/sessions/${id}/actions`, async (route) => {
    if (!injected) {
      injected = true;
      const body = route.request().postDataJSON();
      const concurrent = await page.request.post(`/api/sessions/${id}/actions`, {
        data: {
          request_id: 'concurrent-tab',
          expected_revision: body.expected_revision,
          operation: 'rate',
          rate: 5,
        },
      });
      expect(concurrent.ok()).toBe(true);
    }
    await route.continue();
  });
  await page.getByRole('button', { name: 'Step one second' }).click();
  await expect(page.getByRole('alert')).toContainText('Stale session revision');
  await expect(page.getByTestId('live-clock')).toHaveText('t=0 s');
  await expect(page.getByLabel('Playback speed')).toHaveValue('5');
  await step(page, 1);
  expect((await record(page, id)).frames).toHaveLength(2);
});

test('a lost successful response survives reload and identical retry cannot duplicate a tick', async ({
  page,
}) => {
  const id = await create(page);
  let lost = false;
  await page.route(`**/api/sessions/${id}/actions`, async (route) => {
    if (!lost) {
      lost = true;
      const response = await route.fetch();
      expect(response.ok()).toBe(true);
      await route.abort('failed');
    } else await route.continue();
  });
  await page.getByRole('button', { name: 'Step one second' }).click();
  await expect(page.getByRole('button', { name: 'Retry same request' })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('button', { name: 'Retry same request' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Step one second' })).toBeDisabled();
  await page.getByRole('button', { name: 'Retry same request' }).click();
  await expect(page.getByRole('button', { name: 'Step one second' })).toBeEnabled();
  const run = await record(page, id);
  expect(run.frames).toHaveLength(2);
  expect(run.actions.filter((a: { operation: string }) => a.operation === 'step')).toHaveLength(1);
});

test('read failure blocks controls and exposes cached state until refresh succeeds', async ({
  page,
}) => {
  const id = await create(page);
  await page.route(`**/api/sessions/${id}/simulation`, (route) => route.abort('failed'));
  await expect(page.getByRole('alert')).toContainText('Last displayed time: t=0 s');
  await expect(page.getByRole('button', { name: 'Step one second' })).toBeDisabled();
  await page.unroute(`**/api/sessions/${id}/simulation`);
  await page.getByRole('button', { name: 'Refresh live state' }).click();
  await expect(page.getByRole('button', { name: 'Step one second' })).toBeEnabled();
});

test('mobile keyboard operation, reduced motion, topology selection and analysis fit the viewport', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await create(page);
  await expect(page.getByLabel('Animate energized lines')).not.toBeChecked();
  const transformer = page
    .getByTestId('live-topology')
    .getByRole('button', { name: 'Inspect transformer:tx_a1', exact: true });
  await transformer.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByLabel('Inspect equipment', { exact: true })).toHaveValue(
    'transformer:tx_a1',
  );
  const drawer = page.getByRole('dialog', { name: 'Equipment inspection', exact: true });
  const bounds = await drawer.boundingBox();
  expect(bounds).not.toBeNull();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.y).toBeGreaterThanOrEqual(0);
  expect(bounds!.width).toBeLessThanOrEqual(390);
  expect(bounds!.height).toBeLessThanOrEqual(844);
  await closePanel(page);
  await expect(transformer).toBeFocused();
  await schedule(page);
  await step(page, 1);
  await step(page, 2);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() =>
      page.getByTestId('live-topology').evaluate((canvas) => {
        const bounds = canvas.getBoundingClientRect();
        const nodes = [...canvas.querySelectorAll('.react-flow__node')];
        return (
          nodes.length === 7 &&
          nodes.every((node) => {
            const rect = node.getBoundingClientRect();
            return (
              rect.left >= bounds.left - 1 &&
              rect.right <= bounds.right + 1 &&
              rect.top >= bounds.top - 1 &&
              rect.bottom <= bounds.bottom + 1
            );
          })
        );
      }),
    )
    .toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)).toBe(
    false,
  );
  await page.getByRole('button', { name: 'Incident analysis', exact: true }).click();
  await expect(page.getByRole('table', { name: 'Live incident timeline' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)).toBe(
    false,
  );
});

test('pause commits before a manual step', async ({ page }) => {
  const id = await create(page, 'off', 20);
  await page.getByRole('button', { name: 'Play session', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Pause session', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Pause session', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Step one second', exact: true })).toBeEnabled();
  const before = await record(page, id);
  const tick = before.final.checkpoint.now_s;
  await step(page, tick + 1);
  const after = await record(page, id);
  expect(after.frames.length).toBe(before.frames.length + 1);
  expect(after.final.mode).toBe('paused');
});

test('equipment details preserve raw rows, contain keyboard focus and return focus to the selected node', async ({
  page,
}) => {
  await create(page);
  await expect(page.getByRole('table')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Schedule disturbance', exact: true })).toHaveCount(
    0,
  );
  const asset = page
    .getByTestId('live-topology')
    .getByRole('button', { name: 'Inspect load:a1', exact: true });
  await asset.focus();
  await page.keyboard.press('Enter');
  const dialog = page.getByRole('dialog', { name: 'Equipment inspection', exact: true });
  await expect(dialog).toBeVisible();
  await expect(page.getByLabel('Inspect equipment', { exact: true })).toHaveValue('load:a1');
  await expect(
    dialog.getByRole('table', { name: 'Received measurements', exact: true }),
  ).toContainText('OpenDSS');
  await dialog.getByText('Raw measurement records', { exact: true }).click();
  await expect(dialog.locator('pre')).toContainText('measured_at_s');
  for (let i = 0; i < 10; i++) {
    await page.keyboard.press('Tab');
    expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
  }
  for (let i = 0; i < 10; i++) {
    await page.keyboard.press('Shift+Tab');
    expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
  }
  await closePanel(page);
  await expect(asset).toBeFocused();
  await expect(page.getByTestId('live-clock')).toHaveText('t=0 s');
});

test('closing a disturbance form does not schedule an event or advance the session', async ({
  page,
}) => {
  const id = await create(page);
  await openScenario(page);
  await page.getByLabel('Disturbance type', { exact: true }).selectOption('demand');
  await page.getByLabel('Demand multiplier (×)', { exact: true }).fill('2');
  await closePanel(page);
  await expect(page.getByRole('button', { name: 'Add disturbance', exact: true })).toBeFocused();
  const run = await record(page, id);
  expect(run.frames).toHaveLength(1);
  expect(run.final.checkpoint.future).toEqual([]);
  await openScenario(page);
  await expect(page.getByLabel('Disturbance type', { exact: true })).toHaveValue('demand');
  await expect(page.getByLabel('Demand multiplier (×)', { exact: true })).toHaveValue('2');
  await closePanel(page);
});

test('an uncertain scheduling response can be retried inside its dialog without duplicate events', async ({
  page,
}) => {
  const id = await create(page);
  await openScenario(page);
  let lost = false;
  await page.route(`**/api/sessions/${id}/actions`, async (route) => {
    if (!lost) {
      lost = true;
      const response = await route.fetch();
      expect(response.ok()).toBe(true);
      await route.abort('failed');
    } else await route.continue();
  });
  await page.getByRole('button', { name: 'Schedule disturbance', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Add disturbance', exact: true });
  await expect(dialog.getByRole('alert')).toContainText(
    'Could not confirm whether the server saved',
  );
  await expect(
    dialog.getByRole('button', { name: 'Schedule disturbance', exact: true }),
  ).toBeDisabled();
  await dialog.getByRole('button', { name: 'Retry same request', exact: true }).click();
  await expect(dialog).not.toBeVisible();
  const run = await record(page, id);
  expect(run.frames).toHaveLength(1);
  expect(run.actions.filter((a: { operation: string }) => a.operation === 'schedule')).toHaveLength(
    1,
  );
  await step(page, 1);
  const committed = await record(page, id);
  expect(committed.frames[1].physical_events).toHaveLength(1);
  await expect(page.getByTestId('live-unserved')).toContainText('1,000 kW');
});

test('a new-session dialog creates a distinct saved session without changing the original', async ({
  page,
}) => {
  const original = await create(page, 'off');
  await page.getByRole('button', { name: 'New session', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'New session', exact: true });
  await dialog.getByLabel('Session title', { exact: true }).fill('Second session');
  await dialog.getByLabel('Restoration policy', { exact: true }).selectOption('guarded');
  const created = page.waitForResponse(
    (r) => r.url().endsWith('/api/sessions') && r.request().method() === 'POST',
  );
  await dialog.getByRole('button', { name: 'Create live session', exact: true }).click();
  const receipt = await (await created).json();
  expect(receipt.id).not.toBe(original);
  await expect(dialog).not.toBeVisible();
  await expect(page.getByLabel('Saved live session')).toHaveValue(receipt.id);
  await expect(page.getByTestId('live-clock')).toHaveText('t=0 s');
  const unchanged = await record(page, original);
  expect(unchanged.frames).toHaveLength(1);
  expect(unchanged.definition.control.policy).toBe('off');
});
