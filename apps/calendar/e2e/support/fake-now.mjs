/**
 * Test-only preload for the Next server: freeze its clock at E2E_FROZEN_NOW.
 *
 * Loaded with `NODE_OPTIONS=--import <this file>`, set in playwright.config.ts on the
 * Next `webServer` entry ONLY, so the Playwright runner itself keeps the real clock.
 * See e2e/support/clock.ts for why the suite pins "now" at all.
 *
 * TODO(Ari) — Lesson: Server Components run on the Next SERVER, so which row says
 *   "Today" is decided by the server's clock. Playwright's `page.clock` fakes only
 *   the BROWSER's clock and cannot reach it (B6 plan, K1). The pin therefore goes on
 *   the server process, as this preload, and it patches `Date.now` and ONLY
 *   `Date.now`: the Temporal polyfill reads `Date.now()` for `Temporal.Now`, so one
 *   line is enough, and replacing or subclassing `Date` crashes the app at import
 *   (`TypeError: Date.UTC is not a function`, plan fact 7).
 * Code:
 *   Date.now = () => FROZEN;
 * Check: `pnpm --filter calendar exec playwright test e2e/home.spec.ts` (or
 *   `make e2e`). The Today-row assertion in home.spec.ts goes green when this is
 *   right; until then it fails because the server is on the real clock. Likeliest
 *   mistakes: `globalThis.Date = class extends Date {...}` (crashes the app), or
 *   reaching for `page.clock.install` (browser only).
 *
 * Unlike the usual scaffold, this placeholder is a MISSING LINE, not a `throw`: a
 * throw in a preload kills the Next process, and with it every browser test, so one
 * open gap would redden the whole suite. home.spec.ts is the loud part.
 */
// The lint disable below goes away with the gap: once `Date.now = () => FROZEN` is
// written, FROZEN is used.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
const FROZEN = Date.parse(process.env.E2E_FROZEN_NOW);

// The gap goes here.
