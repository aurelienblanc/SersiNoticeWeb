const { defineConfig } = require('playwright/test');

const python = process.env.SERSI_TEST_PYTHON || 'python';

module.exports = defineConfig({
  testDir: './tests/browser',
  outputDir: './test-results',
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  use: {
    baseURL: 'http://127.0.0.1:8767',
    channel: process.env.SERSI_BROWSER_CHANNEL || undefined,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'pc', use: { viewport: { width: 1440, height: 1000 } } },
    {
      name: 'mobile',
      use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true },
    },
  ],
  webServer: {
    command: `"${python}" tests/browser/server.py`,
    url: 'http://127.0.0.1:8767/health/',
    reuseExistingServer: false,
    timeout: 60000,
  },
});
