import { defineConfig, devices } from "@playwright/test";

/**
 * Smoke and accessibility tests run against the built bundle (`vite preview`) with the API mocked
 * by route interception, so no backend is needed. Set PW_CHANNEL=chrome (or msedge) to drive an installed
 * browser when the bundled Chromium cannot be downloaded.
 */
const channel = process.env.PW_CHANNEL || undefined;

export default defineConfig({
  testDir: "./playwright",
  outputDir: "./test-results",
  fullyParallel: true,
  workers: process.env.CI ? 2 : 3,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], channel } }],
  webServer: {
    command: "npm run build && npx vite preview --host 127.0.0.1 --port 4173 --strictPort",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env.CI,
    timeout: 240_000,
  },
});
