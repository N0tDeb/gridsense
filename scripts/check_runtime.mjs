/** Exercise the built dashboard and native backend using a disposable database. */
import { chromium as playwright } from '../frontend/node_modules/playwright/index.mjs';
import { spawn, execFileSync } from 'node:child_process';
import { mkdir, writeFile, readdir } from 'node:fs/promises';
import { createServer } from 'node:net';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import { parseArgs } from 'node:util';
import { checkLiveDashboard } from './check_live_runtime.mjs';

const root = fileURLToPath(new URL('../', import.meta.url)).replace(/[\\/]$/, '');
const options = parseArgs({
  options: { 'output-dir': { type: 'string', default: root + '/var/runtime-check' } },
});
const output = resolve(options.values['output-dir']);
await mkdir(output, { recursive: true });
if ((await readdir(output)).length) throw new Error('Use a new empty runtime output directory');
const python =
  process.env.GRIDSENSE_PYTHON ?? (process.platform === 'win32' ? 'python' : 'python3');
const environment = { ...process.env };
const reservation = createServer();
await new Promise((ok, fail) => {
  reservation.once('error', fail);
  reservation.listen(0, '127.0.0.1', ok);
});
const port = reservation.address().port;
await new Promise((ok) => reservation.close(ok));
const baseURL = 'http://127.0.0.1:' + port;
const fingerprintCode =
  "import json,sys;sys.path.insert(0,'scripts');from release_support import verification_inputs;print(json.dumps(verification_inputs('.')))";
const inputHashes = JSON.parse(
  execFileSync(python, ['-c', fingerprintCode], { cwd: root, env: environment, encoding: 'utf8' }),
);
const server = spawn(python, [root + '/scripts/test_server.py', '--port', String(port)], {
  cwd: root,
  env: environment,
  stdio: ['ignore', 'pipe', 'pipe'],
});
let serverOutput = '',
  browser;
server.stderr.on('data', (data) => {
  serverOutput += data.toString();
});
const errors = [],
  failedRequests = [];
try {
  let ready = false;
  for (let i = 0; i < 150; i++) {
    if (server.exitCode !== null) throw new Error('Server exited: ' + serverOutput);
    try {
      ready = (await fetch(baseURL + '/api/health')).ok;
    } catch {}
    if (ready) break;
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  if (!ready) throw new Error('Server readiness failed: ' + serverOutput);
  browser = await playwright.launch({
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
    env: environment,
    args: process.env.PLAYWRIGHT_CHROMIUM_ARGS
      ? JSON.parse(process.env.PLAYWRIGHT_CHROMIUM_ARGS)
      : undefined,
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('requestfailed', (request) =>
    failedRequests.push({ url: request.url(), error: request.failure()?.errorText }),
  );
  const health = await page.request.get(baseURL + '/api/health');
  const frontend = await page.goto(baseURL + '/');
  await page.getByText('OpenDSS ready', { exact: true }).waitFor();
  const liveDashboard = await checkLiveDashboard(page, baseURL, output);
  await page.getByRole('button', { name: 'Incident analysis', exact: true }).click();
  await page.getByRole('button', { name: 'Restoration lab', exact: true }).click();
  await page.getByRole('heading', { name: 'Restoration lab', exact: true }).waitFor();
  await page.getByRole('button', { name: 'Run restoration', exact: true }).click();
  await page.locator('.decision-summary').waitFor();
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: output + '/restoration-desktop.png', fullPage: true });
  await page.getByRole('button', { name: 'Decision evidence', exact: true }).click();
  await page.getByRole('button', { name: 'Show raw records', exact: true }).click();
  await page.screenshot({ path: output + '/evidence-desktop.png', fullPage: true });
  await page.getByRole('button', { name: 'Controller tests', exact: true }).click();
  const regressionResponse = page.waitForResponse(
    (r) => r.url().endsWith('/api/verification/regressions') && r.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Compare controllers', exact: true }).click();
  const regression = await (await regressionResponse).json();
  await page
    .getByRole('heading', { name: 'Requirements met · no service regression', exact: true })
    .waitFor();
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: output + '/regression-desktop.png', fullPage: true });
  const desktopOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > innerWidth + 1,
  );
  const regReplay = await (
    await page.request.post(baseURL + '/api/verification/records/' + regression.id + '/replay')
  ).json();
  const regExport = await page.request.get(
    baseURL + '/api/verification/records/' + regression.id + '/export',
  );
  await writeFile(output + '/regression-export.json', await regExport.text());
  await page.getByRole('button', { name: 'Switch confirmation', exact: true }).click();
  await page.getByRole('spinbutton', { name: 'Event sequences to test', exact: true }).fill('4');
  const temporalResponse = page.waitForResponse(
    (r) => r.url().endsWith('/api/verification/temporal') && r.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Search switch failures', exact: true }).click();
  const temporal = await (await temporalResponse).json();
  await page
    .getByRole('heading', { name: 'False restoration claim reproduced', exact: true })
    .waitFor();
  await page.screenshot({ path: output + '/temporal-desktop.png', fullPage: true });
  const tempReplay = await (
    await page.request.post(baseURL + '/api/verification/records/' + temporal.id + '/replay')
  ).json();
  const tempExport = await page.request.get(
    baseURL + '/api/verification/records/' + temporal.id + '/export',
  );
  await writeFile(output + '/temporal-export.json', await tempExport.text());
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: output + '/temporal-mobile.png', fullPage: true });
  const mobileOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > innerWidth + 1,
  );
  await page.getByRole('button', { name: 'Controller comparison', exact: true }).click();
  await page.getByRole('button', { name: 'Compare controllers', exact: true }).click();
  await page
    .getByRole('heading', { name: 'Requirements met · no service regression', exact: true })
    .waitFor();
  await page.screenshot({ path: output + '/regression-mobile.png', fullPage: true });
  await page.getByRole('button', { name: 'IEEE feeder check', exact: true }).click();
  const referenceResponse = page.waitForResponse((r) =>
    r.url().endsWith('/api/verification/reference'),
  );
  await page.getByRole('button', { name: 'Validate IEEE feeder', exact: true }).click();
  const reference = await (await referenceResponse).json();
  await page.getByText('Reference check passed', { exact: true }).waitFor();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({ path: output + '/reference-desktop.png', fullPage: true });
  const searchResponse = await page.request.post(baseURL + '/api/failure-searches', {
    data: { seed: 42, budget: 24, reduction_budget: 48 },
    timeout: 120000,
  });
  if (searchResponse.status() !== 201)
    throw new Error('Search request failed: ' + (await searchResponse.text()));
  const search = await searchResponse.json();
  const searchExport = await page.request.get(
    baseURL + '/api/failure-searches/' + search.id + '/export',
  );
  await writeFile(output + '/failure-search-export.json', await searchExport.text());
  const searchReplay = await (
    await page.request.post(baseURL + '/api/failure-searches/' + search.id + '/replay')
  ).json();
  if (!searchReplay.matched) throw new Error('Search replay failed');
  const sessionResponse = await page.request.post(baseURL + '/api/sessions', {
    data: {
      request_id: 'runtime-session',
      config: {
        horizon_s: 2,
        events: [
          {
            kind: 'outage',
            at_s: 1,
            incident_id: 'transformer',
            equipment_kind: 'transformer',
            equipment: 'tx_a1',
          },
          { kind: 'repair', at_s: 2, incident_id: 'transformer' },
        ],
      },
    },
  });
  if (sessionResponse.status() !== 201) throw new Error('Session creation failed');
  let session = await sessionResponse.json();
  const sessionURL = baseURL + '/api/sessions/' + session.id;
  for (let i = 0; i < 2; i++) {
    const response = await page.request.post(sessionURL + '/actions', {
      data: { request_id: 'step-' + i, expected_revision: session.revision, operation: 'step' },
    });
    if (!response.ok()) throw new Error('Session step failed: ' + (await response.text()));
    session = await response.json();
  }
  const sessionExport = await page.request.get(sessionURL + '/export');
  const sessionRecord = await sessionExport.json();
  await writeFile(
    output + '/live-session-export.json',
    JSON.stringify(sessionRecord, null, 2) + '\n',
  );
  const sessionReplay = await (await page.request.post(sessionURL + '/replay')).json();
  const last = sessionRecord.frames.at(-1);
  if (
    !sessionReplay.matched ||
    last.physical.equipment_outages.length ||
    !last.physical.open_transformers.includes('tx_a1') ||
    Math.abs(last.electrical.unserved_kw - 400) > 0.001
  )
    throw new Error('Live session outage/repair/replay contract failed');
  const controlledResponse = await page.request.post(baseURL + '/api/sessions', {
    data: {
      request_id: 'runtime-controlled',
      config: {
        horizon_s: 7,
        control: { policy: 'nominal' },
        events: [
          {
            kind: 'outage',
            at_s: 1,
            incident_id: 'feeder',
            equipment_kind: 'line',
            equipment: 'feed_a',
          },
          { kind: 'repair', at_s: 4, incident_id: 'feeder' },
        ],
      },
    },
  });
  if (controlledResponse.status() !== 201) throw new Error('Controlled session creation failed');
  let controlled = await controlledResponse.json();
  const controlledURL = baseURL + '/api/sessions/' + controlled.id;
  for (let i = 0; i < 7; i++) {
    const response = await page.request.post(controlledURL + '/actions', {
      data: {
        request_id: 'controlled-' + i,
        expected_revision: controlled.revision,
        operation: 'step',
      },
    });
    if (!response.ok()) throw new Error('Controlled step failed: ' + (await response.text()));
    controlled = await response.json();
  }
  const controlledExport = await page.request.get(controlledURL + '/export');
  const controlledRecord = await controlledExport.json();
  await writeFile(
    output + '/controlled-session-export.json',
    JSON.stringify(controlledRecord, null, 2) + '\n',
  );
  const controlledReplay = await (await page.request.post(controlledURL + '/replay')).json();
  const control = controlledRecord.frames.at(-1).control;
  if (
    !controlledReplay.matched ||
    control.supply_status !== 'normal_supply_verified' ||
    Object.values(control.commands).length !== 3 ||
    Object.values(control.commands).some((command) => command.status !== 'confirmed') ||
    !controlledRecord.frames.some(
      (frame) => frame.control.supply_status === 'alternate_supply_verified',
    )
  )
    throw new Error('Controlled restoration/confirmation/recovery/replay contract failed');
  const result = {
    verified_inputs: inputHashes,
    live_dashboard: liveDashboard,
    search: {
      id: search.id,
      status: search.status,
      replay: searchReplay,
      export_status: searchExport.status(),
    },
    verified_at: new Date().toISOString(),
    frontend_status: frontend.status(),
    health_status: health.status(),
    health: await health.json(),
    live_session: {
      id: session.id,
      ticks: session.at_s,
      mode: session.mode,
      replay: sessionReplay,
      export_status: sessionExport.status(),
      final_unserved_kw: last.electrical.unserved_kw,
      repaired_transformer_still_isolated: true,
    },
    controlled_session: {
      id: controlled.id,
      ticks: controlled.at_s,
      replay: controlledReplay,
      export_status: controlledExport.status(),
      supply_status: control.supply_status,
      commands: Object.values(control.commands),
      metrics: controlledRecord.frames.at(-1).metrics,
    },
    regression: {
      id: regression.id,
      accepted: regression.accepted,
      baseline: regression.baseline.action.id,
      candidate: regression.candidate.action.id,
      replay: regReplay,
      export_status: regExport.status(),
    },
    temporal: {
      id: temporal.id,
      status: temporal.status,
      reduction: temporal.reduction,
      replay: tempReplay,
      export_status: tempExport.status(),
    },
    reference,
    viewport_checks: {
      ...liveDashboard.viewport_checks,
      desktop_1440: { overflow: desktopOverflow },
      mobile_390: { overflow: mobileOverflow },
    },
    javascript_errors: errors,
    failed_requests: failedRequests,
  };
  const finalHashes = JSON.parse(
    execFileSync(python, ['-c', fingerprintCode], {
      cwd: root,
      env: environment,
      encoding: 'utf8',
    }),
  );
  if (JSON.stringify(finalHashes) !== JSON.stringify(inputHashes))
    throw new Error('Verification inputs changed during runtime check');
  await writeFile(output + '/runtime.json', JSON.stringify(result, null, 2) + '\n');
  console.log(
    JSON.stringify({
      frontend: frontend.status(),
      backend: health.status(),
      regression: regression.accepted,
      temporal: temporal.status,
      reference: reference.passed,
      desktopOverflow,
      mobileOverflow,
      errors,
      failedRequests,
    }),
  );
  if (
    !regReplay.matched ||
    !tempReplay.matched ||
    !reference.passed ||
    desktopOverflow ||
    mobileOverflow ||
    errors.length ||
    failedRequests.length
  )
    throw new Error('Runtime check failed');
} finally {
  if (browser) await browser.close();
  if (server.exitCode === null) {
    const stopped = new Promise((resolve) => server.once('close', resolve));
    server.kill('SIGTERM');
    await stopped;
  }
}
