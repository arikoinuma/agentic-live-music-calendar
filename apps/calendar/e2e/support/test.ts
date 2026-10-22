/**
 * The `test` and `expect` every spec imports, from one place.
 *
 * Specs import from here rather than from `@playwright/test` so that behaviour every
 * test needs reaches all of them without editing each file. One is
 * letting the page's in-flight requests finish before the browser closes.
 * A second: the delay proxy's reset, so no test leaves the API slow or broken for the next.
 */
import { expect, test as base, type Request } from "@playwright/test";
import { PROXY_URL, WEB_URL } from "./stack";

export { expect };

/** What a test can do to the API behind Next, through the delay proxy (delay-proxy.mjs). */
export type Stack = {
  /** Answer every API request after `ms` milliseconds. */
  delay: (ms: number) => Promise<void>;
  /** Answer every API request with a 502, as an outage would. */
  fail: () => Promise<void>;
  /** Back to a plain pass-through. */
  reset: () => Promise<void>;
};

// A valid 1x1 transparent PNG, served in place of any image from outside the app (below).
const TINY_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
  "base64",
);

const control = async (path: string) => {
  const response = await fetch(`${PROXY_URL}${path}`, { method: "POST" });
  if (!response.ok) throw new Error(`delay proxy ${path} answered ${response.status}`);
};

export const test = base.extend<{ stack: Stack }>({
  // The proxy's mode is global, so a test that slows or breaks the API must never
  // leave it that way for the next one. `auto` runs this for EVERY test, even one
  // that never asks for `stack`, and the reset is in the teardown, so it happens
  // whether the test passed, failed or timed out.
  stack: [
    // Playwright finds a fixture's dependencies by reading its first parameter as an
    // object pattern, so the empty `{}` is required even though nothing is used.
    // eslint-disable-next-line no-empty-pattern
    async ({}, use) => {
      await use({
        delay: (ms) => control(`/__delay/${ms}`),
        fail: () => control("/__fail"),
        reset: () => control("/__reset"),
      });
      await control("/__reset");
    },
    { auto: true },
  ],

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
  page: async ({ page, stack }, use) => {
    // HERMETIC: nothing a test does may reach the internet. The sample data's poster and
    // photo URLs point at example.com, so show and venue pages would otherwise fetch real
    // images (slow, and a failure in CI or a sandbox with no route out). Images from outside
    // the app are answered with a 1x1 PNG, so layout and `alt` text behave as with a real
    // image; any other outside request is refused.
    const appOrigin = new URL(WEB_URL).origin;
    await page.route(
      (url) => url.origin !== appOrigin,
      (route) =>
        route.request().resourceType() === "image"
          ? route.fulfill({ contentType: "image/png", body: TINY_PNG })
          : route.abort(),
    );

    const inFlight = new Set<Request>();
    page.on("request", (request) => inFlight.add(request));
    const settled = (request: Request) => inFlight.delete(request);
    page.on("requestfinished", settled);
    page.on("requestfailed", settled);

    await use(page);

    // Drop any delay or failure FIRST. A test that slowed the API would otherwise make
    // the wait below sit out its whole timeout while the prefetches crawl (the proxy is
    // still delaying them), and the browser would close on them anyway. Requests already
    // started finish within the delay they were given; new ones go straight through.
    await stack.reset();

    await expect
      .poll(() => inFlight.size, { timeout: 5_000, message: "requests still in flight at test end" })
      .toBe(0)
      .catch(() => {
        // Do not fail the test, but leave a trace: a request that is still going after five
        // seconds is itself worth knowing about, and would otherwise be invisible.
        test.info().annotations.push({
          type: "requests still in flight at teardown",
          description: [...inFlight].map((r) => r.url()).join("\n"),
        });
      });
  },
});
