/**
 * Test-only preload for the Next server: freeze its clock at E2E_FROZEN_NOW.
 *
 * Loaded with `NODE_OPTIONS=--import <this file>`, set in playwright.config.ts on the
 * Next `webServer` entry ONLY, so the Playwright runner itself keeps the real clock.
 * See e2e/support/clock.ts for why the suite pins "now" at all.
 *
 *   Server Components run on the Next SERVER, so which row says
 *   "Today" is decided by the server's clock. Playwright's `page.clock` fakes only
 *   the BROWSER's clock and cannot reach it (B6-K1). The pin therefore goes on
 *   the server process, as this preload, and it patches `Date.now` and ONLY
 *   `Date.now`: the Temporal polyfill reads `Date.now()` for `Temporal.Now`, so one
 *   line is enough, and replacing or subclassing `Date` crashes the app at import
 *   (`TypeError: Date.UTC is not a function`, plan fact 7).
 */
const FROZEN = Date.parse(process.env.E2E_FROZEN_NOW);
Date.now = () => FROZEN;

// Fail LOUDLY at startup if the pin is missing or not a date. Otherwise `Date.now()` would
// return NaN once the gap below is written, `Temporal.Now` would throw on every page, and
// the whole suite would go red far from the cause.
if (Number.isNaN(FROZEN)) {
  throw new Error(`E2E_FROZEN_NOW must be an ISO instant (see e2e/support/clock.ts); got ${process.env.E2E_FROZEN_NOW}`);
}

// The gap goes here.
