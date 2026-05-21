import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: "html",
  use: {
    baseURL: "http://localhost:5173",
    trace: "on-first-retry",
    screenshot: "on",
  },
  projects: [
    {
      name: "chromium",
      testDir: "./e2e",
      testIgnore: /integration/,
      use: { ...devices["Desktop Chrome"] },
      webServer: {
        command: "npx vite --host 0.0.0.0 --port 5173",
        url: "http://localhost:5173",
        reuseExistingServer: true,
        timeout: 30_000,
      },
    },
    {
      name: "integration",
      testDir: "./e2e/integration",
      use: { ...devices["Desktop Chrome"], baseURL: process.env.INTEGRATION_BASE_URL || "http://localhost:5173" },
      // No webServer — assumes Docker Compose is already running
    },
  ],
});
