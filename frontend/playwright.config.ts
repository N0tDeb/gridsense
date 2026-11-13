import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  timeout: 45_000,
  expect: { timeout: 15_000 },
  reporter: process.env.GRIDSENSE_BROWSER_REPORT
    ? [['list'], ['json', { outputFile: process.env.GRIDSENSE_BROWSER_REPORT }]]
    : [['list']],
  use: {
    baseURL: 'http://127.0.0.1:8001',
    browserName: 'chromium',
    viewport: { width: 1440, height: 1000 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    launchOptions: {
      executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
      args: process.env.PLAYWRIGHT_CHROMIUM_ARGS
        ? JSON.parse(process.env.PLAYWRIGHT_CHROMIUM_ARGS)
        : undefined,
    },
  },
  webServer: {
    command: `"${process.env.GRIDSENSE_PYTHON ?? (process.platform === 'win32' ? 'python' : 'python3')}" ../scripts/test_server.py`,
    url: 'http://127.0.0.1:8001/api/health',
    timeout: 60_000,
    reuseExistingServer: false,
  },
});
