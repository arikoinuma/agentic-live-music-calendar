/**
 * The one instant the end-to-end suite pins the Next server's clock to (B6-D2).
 *
 * Why pinned: the home page marks the row for "today" (`aria-current="date"` and a
 * "Today" badge), and "today" is decided by the Next SERVER's clock in the metro's
 * timezone (`metroToday` in lib/dates.ts). The API's window is already fixed to
 * the sample data (`data.START` in apps/api/app/sample_data.py), so this is the one
 * thing in the app that follows the real calendar. Left alone, a test that expects
 * a particular Today row passes on some days and fails on the rest.
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
