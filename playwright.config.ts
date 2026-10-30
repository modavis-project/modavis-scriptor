import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.SCRIPTOR_TEST_BASE_URL || "http://127.0.0.1:3410";
const target = new URL(baseURL);
if (
  target.protocol !== "http:" ||
  !["127.0.0.1", "localhost", "[::1]"].includes(target.hostname) ||
  !target.port ||
  Number(target.port) <= 1024 ||
  ["3000", "8010", "3080", "8080"].includes(target.port) ||
  target.username || target.password || target.search || target.hash || target.pathname !== "/"
) {
  throw new Error("Browser QA requires a loopback disposable test URL; research ports are forbidden.");
}

export default defineConfig({
  testDir: "./tests/browser",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  reporter: "list",
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "firefox", use: { ...devices["Desktop Firefox"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
  ],
});
