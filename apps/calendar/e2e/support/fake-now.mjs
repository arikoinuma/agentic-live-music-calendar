/**
 * Test-only preload for the Next server: freeze its clock at E2E_FROZEN_NOW.
 *
 * Loaded with `NODE_OPTIONS=--import <this file>`, set in playwright.config.ts on the
 * Next `webServer` entry ONLY, so the Playwright runner itself keeps the real clock.
 * See e2e/support/clock.ts for why the suite pins "now" at all.
 *
 * Why a preload on the server and not a Playwright clock (B6-K1): Server Components run on
 * the Next SERVER, so which row says "Today" is decided by the server's clock, and
 * Playwright's `page.clock` fakes only the BROWSER's. It patches `Date.now` and ONLY
 * `Date.now`: the Temporal polyfill reads `Date.now()` for `Temporal.Now`, so one line is
 * enough, and replacing or subclassing `Date` crashes the app at import
 * (`TypeError: Date.UTC is not a function`, notes.md).
 */
const FROZEN = Date.parse(process.env.E2E_FROZEN_NOW);
Date.now = () => FROZEN;

// Fail LOUDLY at startup if the pin is missing or not a date. Otherwise `Date.now()` would
// return NaN, `Temporal.Now` would throw on every page, and the whole suite would go red far
// from the cause.
if (Number.isNaN(FROZEN)) {
  throw new Error(`E2E_FROZEN_NOW must be an ISO instant (see e2e/support/clock.ts); got ${process.env.E2E_FROZEN_NOW}`);
}
