/**
 * The `test` and `expect` every spec imports, from one place.
 *
 * Specs import from here rather than from `@playwright/test` so that behaviour every
 * test needs reaches all of them without editing each file. Today that is one
 * thing: letting the page's in-flight requests finish before the browser closes.
 * (The delay proxy's reset joins it in Step 4 of the B6 plan.)
 */
import { expect, test as base, type Request } from "@playwright/test";

export { expect };

export const test = base.extend({
  // WHY THIS EXISTS. A production Next page PREFETCHES the pages its links point to
  // (the `[RSC] [prefetch]` requests), and those are streamed responses. A test that
  // ends while one is mid-stream closes the browser on it, React in the Next server
  // sees the connection drop, aborts that render and logs
  // `⨯ Error: The destination stream closed early.` The error is harmless (nothing was
  // waiting for that response) but it looks alarming in every run and could hide a real
  // server error in the same output.
  //
  // So after the test body, wait for the requests the page started to finish, and only
  // then let the browser close. Prefetching still happens: the suite sees what a visitor
  // gets, rather than switching the optimisation off. Best effort: a request that never
  // ends must not fail a test, so the wait gives up after a few seconds.
  page: async ({ page }, use) => {
    const inFlight = new Set<Request>();
    page.on("request", (request) => inFlight.add(request));
    const settled = (request: Request) => inFlight.delete(request);
    page.on("requestfinished", settled);
    page.on("requestfailed", settled);

    await use(page);

    await expect
      .poll(() => inFlight.size, { timeout: 5_000, message: "requests still in flight at test end" })
      .toBe(0)
      .catch(() => {});
  },
});
