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
import { fileURLToPath, pathToFileURL } from "node:url";
import { defineConfig, devices } from "@playwright/test";
import { E2E_API_NOW, E2E_NOW } from "./e2e/support/clock";
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
  // A committed `test.only` would make CI pass on ONE test and switch every scan off, so
  // under CI it is an error rather than a filter.
  forbidOnly: !!process.env.CI,
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
      // The real API on a real Postgres loaded with the sample world, its clock frozen (C2-D2, C2-D7). The
      // first command rebuilds the throwaway `calendar_e2e` database (drop, migrate, load) and refuses any
      // other database; the second starts the production app through `app.testing.e2e_app`, which pins
      // `get_now` to E2E_API_NOW and refuses to start unpinned. `exec` makes uvicorn replace the shell, so
      // the process tree matches the other two servers'; Playwright signals the whole group on shutdown
      // either way. DATABASE_URL is set here, explicitly, so a developer's apps/api/.env (which may point at
      // a real database) is never read. E2E_DATABASE_URL overrides the default for a different local port or
      // credentials (CI's service uses the default). `Settings()` insists on MODEL_NAME at import.
      command:
        "uv run python -m app.testing.e2e_database && " +
        `exec uv run uvicorn app.testing.e2e_app:app --host 127.0.0.1 --port ${API_PORT}`,
      cwd: "../api",
      env: {
        DATABASE_URL:
          process.env.E2E_DATABASE_URL ?? "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/calendar_e2e",
        MODEL_NAME: "e2e-placeholder",
        E2E_API_FROZEN_NOW: E2E_API_NOW,
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
      env: {
        API_BASE_URL: PROXY_URL,
        // The status page shows the frontend's environment and reports an invalid one as an error line
        // (C3-D7); the stack is a local one, so say so instead of scanning an error state.
        APP_ENV: "local",
        // Freeze this process's clock (e2e/support/clock.ts says why). `NODE_OPTIONS` is
        // set here, on the Next server only, so the Playwright runner keeps the real clock.
        // A file URL, not a path, because `--import` wants one on Windows.
        E2E_FROZEN_NOW: E2E_NOW,
        NODE_OPTIONS: `--import ${pathToFileURL(fileURLToPath(new URL("./e2e/support/fake-now.mjs", import.meta.url))).href}`,
      },
      url: WEB_URL,
      reuseExistingServer: false,
      gracefulShutdown: shutdown,
      timeout: 60_000,
    },
  ],
});
