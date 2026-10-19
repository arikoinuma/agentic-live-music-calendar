/**
 * Playwright configuration for the end-to-end suite (B6 plan,
 * docs/dev/implementations/b6-accessibility-and-e2e.md, "Design of the harness").
 *
 * `playwright test` starts the whole stack itself (the three `webServer`
 * entries below), runs the specs in one real Chromium, and stops the servers.
 * The app must be BUILT first: this runs `next start`, not `next dev`, so the
 * suite sees what a visitor gets (decision B6-D3). `make e2e` builds, then runs.
 */
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { defineConfig, devices } from "@playwright/test";
import { API_PORT, API_URL, PROXY_PORT, PROXY_URL, WEB_PORT, WEB_URL } from "./e2e/support/stack";

// Fail early, with the fix in the message, rather than with a Next error buried in
// a webServer timeout. `next start` needs a production build.
if (!existsSync(fileURLToPath(new URL("./.next/BUILD_ID", import.meta.url)))) {
  throw new Error("No production build found. Run `pnpm --filter calendar build` first (`make e2e` does).");
}

// What to give each server when Playwright stops it: SIGTERM, then a few seconds.
// `uv run uvicorn` is a parent and a child; this is what lets both go.
const shutdown = { signal: "SIGTERM", timeout: 5_000 } as const;

export default defineConfig({
  testDir: "./e2e",
  // Playwright's DEFAULT also matches `*.test.ts`, which here are Vitest unit tests
  // (they import `vitest` and cannot load under Playwright). Specs are `*.spec.ts`.
  testMatch: "**/*.spec.ts",

  // One worker, tests in file order. The delay proxy holds global state (Step 4),
  // and the ports are fixed, so parallel tests would interfere.
  fullyParallel: false,
  workers: 1,
  // No retries. A retry that turns a flaky red into green hides exactly what the
  // "three green runs in a row" rule exists to catch.
  retries: 0,

  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",

  use: {
    baseURL: WEB_URL,
    trace: "retain-on-failure",
  },

  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        // The sandbox cannot download Playwright's own browser and ships an older
        // Chromium; point at it here. Unset (CI, a laptop after `playwright install
        // chromium`) means Playwright's own.
        launchOptions: { executablePath: process.env.E2E_CHROMIUM_PATH || undefined },
      },
    },
  ],

  // Started in this order, each waited for until its `url` answers. Never reuse a
  // server that is already running: a dev stack has different data and a real clock.
  webServer: [
    {
      // The real API on its sample data. No database is needed: the routers serve
      // `app/sample_data.py` (B6-D1). `Settings()` insists on two variables at import,
      // so give it placeholders; nothing ever connects to that URL.
      command: `uv run uvicorn app.main:app --host 127.0.0.1 --port ${API_PORT}`,
      cwd: "../api",
      env: {
        DATABASE_URL: "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/e2e_unused",
        MODEL_NAME: "e2e-placeholder",
      },
      url: `${API_URL}/health`,
      reuseExistingServer: false,
      gracefulShutdown: shutdown,
      timeout: 60_000,
    },
    {
      command: `node e2e/support/delay-proxy.mjs ${PROXY_PORT} ${API_PORT}`,
      url: `${PROXY_URL}/health`,
      reuseExistingServer: false,
      gracefulShutdown: shutdown,
    },
    {
      // Next reads the API's address from API_BASE_URL (lib/api.ts), here the proxy.
      command: `pnpm exec next start --hostname 127.0.0.1 --port ${WEB_PORT}`,
      env: { API_BASE_URL: PROXY_URL },
      url: WEB_URL,
      reuseExistingServer: false,
      gracefulShutdown: shutdown,
      timeout: 60_000,
    },
  ],
});
