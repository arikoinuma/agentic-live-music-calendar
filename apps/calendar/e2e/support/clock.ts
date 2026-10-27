/**
 * The one instant the end-to-end suite pins the Next server's clock to (B6-D2).
 *
 * Why pinned: the home page marks the row for "today" (`aria-current="date"` and a
 * "Today" badge), and "today" is decided by the Next SERVER's clock in the metro's
 * timezone (`metroToday` in lib/dates.ts). Left alone, a test that expects a
 * particular Today row passes on some days and fails on the rest.
 *
 * Why this instant: 17:00 UTC is noon on Wednesday, October 7, 2026 in Minneapolis,
 * inside the sample window (Sep 28 - Oct 25) on a day that holds five shows.
 * `clock.test.ts` fails if a change to the sample data moves the window away from
 * it, which is what makes "move the pin in the same change" a red test.
 *
 * Read by `playwright.config.ts`, which hands it to `fake-now.mjs` in the Next
 * process. Not read by the tests themselves: they assert on what the page shows.
 */
export const E2E_NOW = "2026-10-07T17:00:00Z";

/**
 * The instant the end-to-end API's clock is pinned to (C2-D2).
 *
 * Since C2 the API reads a real clock (the metro's local date starts the default window),
 * so the job pins it too, in `apps/api/app/testing/e2e_app.py`. It is pinned to NOON on the
 * sample's START date, September 28 (17:00 UTC is noon CDT), not to `E2E_NOW`: that keeps the
 * served window at Sep 28 - Oct 25, exactly what `lib/fixtures` and the specs were written
 * against, and leaves "Today" (October 7, Next's clock) in the MIDDLE of the window, the only
 * place the Today row can be tested. The cost is that the job runs the API nine days "earlier"
 * than Next, which production never does; the Python route tests cover the real single clock.
 *
 * `clock.test.ts` fails if this stops being the date the fixture's window starts on.
 */
export const E2E_API_NOW = "2026-09-28T17:00:00Z";
