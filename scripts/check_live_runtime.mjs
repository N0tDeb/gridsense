import { readFile, writeFile } from 'node:fs/promises';

/** Exercise real browser controls and retain the recorded native states. */
export async function checkLiveDashboard(page, baseURL, output) {
  const button = (name) => page.getByRole('button', { name, exact: true });
  await page.getByRole('heading', { name: 'Live Grid', exact: true }).waitFor();
  await page.getByLabel('Session duration (s)', { exact: true }).fill('8');
  const creation = page.waitForResponse(
    (r) => r.url().endsWith('/api/sessions') && r.request().method() === 'POST',
  );
  await button('Create live session').click();
  const response = await creation;
  if (response.status() !== 201) throw new Error('Live UI session creation failed');
  const receipt = await response.json();
  const path = `${baseURL}/api/sessions/${receipt.id}`;
  await page.getByTestId('live-clock').filter({ hasText: 't=0 s' }).waitFor();
  await page.evaluate(() => document.fonts.ready);
  const milestones = [];
  async function checkConnections() {
    await page.waitForFunction(() => {
      const canvas = document.querySelector('[data-testid="live-topology"]');
      if (!canvas) return false;
      const nodes = [...canvas.querySelectorAll('.react-flow__node')].map((node) =>
        node.getBoundingClientRect(),
      );
      const labels = [...canvas.querySelectorAll('.react-flow__edge-textwrapper')];
      return (
        nodes.length === 7 &&
        labels.length === 8 &&
        canvas.querySelectorAll('.react-flow__edge-path').length === 8 &&
        labels.every((label) => {
          const rect = label.getBoundingClientRect();
          return nodes.every(
            (node) =>
              rect.right <= node.left + 1 ||
              rect.left >= node.right - 1 ||
              rect.bottom <= node.top + 1 ||
              rect.top >= node.bottom - 1,
          );
        })
      );
    });
  }
  async function snapshot(label) {
    await checkConnections();
    const response = await page.request.get(path + '/simulation');
    if (!response.ok()) throw new Error('Live UI state is unreadable');
    const state = await response.json();
    milestones.push({
      label,
      tick: state.at_s,
      supply_status: state.control.supply_status,
      controller_status: state.control.status,
      unserved_kw: state.simulation.electrical?.unserved_kw,
      incidents: state.simulation.physical.equipment_outages,
    });
    return state;
  }
  const healthy = await snapshot('healthy');
  await page.screenshot({
    path: output + '/live-healthy-desktop.png',
    fullPage: true,
  });
  if (healthy.control.supply_status !== 'normal_supply_verified')
    throw new Error('Live UI did not start healthy');
  await button('Add disturbance').click();
  await page.getByLabel('Schedule simulated repair', { exact: true }).check();
  await page.getByLabel('Repair delay after outage (s)', { exact: true }).fill('4');
  const scheduled = page.waitForResponse(
    (r) => r.url() === path + '/actions' && r.request().method() === 'POST',
  );
  await button('Schedule disturbance').click();
  if (!(await scheduled).ok()) throw new Error('Live UI event scheduling failed');
  async function step(at) {
    await button('Step one second').click();
    await page.waitForFunction(
      (tick) => document.querySelector('[data-testid="live-clock"]')?.textContent === `t=${tick} s`,
      at,
    );
  }
  await step(1);
  const outage = await snapshot('isolated');
  if (
    Math.abs(outage.simulation.electrical.unserved_kw - 1000) > 0.001 ||
    outage.control.commands['command-1'].status !== 'pending'
  )
    throw new Error('Live UI isolation/pending command mismatch');
  await page.screenshot({
    path: output + '/live-outage-desktop.png',
    fullPage: true,
  });
  await step(2);
  const backup = await snapshot('backup');
  if (
    backup.control.supply_status !== 'alternate_supply_verified' ||
    backup.simulation.physical.equipment_outages.length !== 1
  )
    throw new Error('Live UI confused alternate supply with repair');
  await page.screenshot({
    path: output + '/live-backup-desktop.png',
    fullPage: true,
  });
  await button('View alarms').click();
  await page.locator('.live-alarm').first().locator(':scope > summary').click();
  await page.screenshot({ path: output + '/alarms-desktop.png', fullPage: true });
  await page.keyboard.press('Escape');
  await button('Inspect equipment').click();
  await page.screenshot({ path: output + '/equipment-desktop.png', fullPage: true });
  await page.keyboard.press('Escape');
  await page.locator('.live-operation-layout').screenshot({
    path: output + '/live-overview-desktop.png',
  });
  await step(3);
  await step(4);
  await step(5);
  const repair = await snapshot('repair');
  if (
    repair.simulation.physical.equipment_outages.length ||
    repair.simulation.physical.closed_lines.includes('feed_a')
  )
    throw new Error('Live UI repair bypassed switching');
  await step(6);
  await snapshot('break-before-make');
  await step(7);
  const recovered = await snapshot('normal');
  if (recovered.control.supply_status !== 'normal_supply_verified')
    throw new Error('Live UI recovery failed');
  await page.screenshot({
    path: output + '/live-recovery-desktop.png',
    fullPage: true,
  });
  const fits = () => page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
  const desktopOverflow = await fits();
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForFunction(() => {
    const canvas = document.querySelector('[data-testid="live-topology"]');
    if (!canvas) return false;
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
  });
  await checkConnections();
  await page.screenshot({ path: output + '/live-mobile.png', fullPage: true });
  await button('Inspect equipment').click();
  await page.getByLabel('Inspect equipment', { exact: true }).selectOption('transformer:tx_a1');
  await page.screenshot({ path: output + '/equipment-mobile.png', fullPage: true });
  await page.keyboard.press('Escape');
  const mobileOverflow = await fits();
  await button('View incident timeline').click();
  await page.getByRole('table', { name: 'Live incident timeline' }).waitFor();
  await button('Inspect tick 1').click();
  await page.getByRole('heading', { name: 'Recorded tick 1 s', exact: true }).waitFor();
  await page.screenshot({
    path: output + '/live-analysis-mobile.png',
    fullPage: true,
  });
  const analysisOverflow = await fits();
  const checked = page.waitForResponse((r) => r.url() === path + '/replay');
  await button('Check session replay').click();
  const replayResponse = await checked;
  const replay = await replayResponse.json();
  if (!replayResponse.ok() || !replay.matched || replay.ticks !== 7)
    throw new Error('Live UI replay failed');
  const downloaded = page.waitForEvent('download');
  await button('Export captured session').click();
  const download = await downloaded;
  const record = JSON.parse(await readFile(await download.path(), 'utf8'));
  if (
    record.id !== receipt.id ||
    record.frames.length !== 8 ||
    record.frames.at(-1).metrics.position_changes !== 3
  )
    throw new Error('Live UI export mismatch');
  await writeFile(output + '/live-dashboard-export.json', JSON.stringify(record, null, 2) + '\n');
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({
    path: output + '/live-analysis-desktop.png',
    fullPage: true,
  });
  if (desktopOverflow || mobileOverflow || analysisOverflow)
    throw new Error('Live UI document overflow');
  return {
    id: receipt.id,
    ticks: 7,
    topology_connections: 8,
    topology_labels_clear: true,
    milestones,
    replay,
    export_status: 200,
    export_sha256: record.content_sha256,
    viewport_checks: {
      live_desktop_1440: { overflow: desktopOverflow },
      live_mobile_390: { overflow: mobileOverflow },
      live_analysis_mobile_390: { overflow: analysisOverflow },
    },
  };
}
