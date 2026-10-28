/**
 * Journey J1 (B6 plan, "Browser tests"): the home page, loaded through a real
 * browser, a real Next server and the real API.
 *
 * Step 1 of the plan was one green test; Step 2 adds the pinned clock. Later steps
 * add the other journeys beside it.
 */
import { expect, test } from "./support/test";

// Proves: the whole stack is wired end to end. Next renders the home page, its
// Server Components fetch from the API (which a browser-side mock could never
// stand in for, because the fetch happens on the Next server), and the calendar
// comes back with at least one show. Fails if any of the three servers is down,
// if the page 500s, or if the streamed calendar never replaces the skeleton:
// the article only exists once the real content has arrived.
test("the home page shows the calendar", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { level: 1, name: "Live music" })).toBeVisible();
  await expect(page.getByRole("article").first()).toBeVisible();
});

// Proves: the Next server's clock is pinned (e2e/support/clock.ts, B6-D2), so the
// "Today" row is the same row on every day the suite runs. With the real clock this
// would be whatever today is, or no row at all once today leaves the sample window.
// It also pins what the calendar holds: 25 shows over the window, five of them on
// the pinned Wednesday. Expected values (written out, not read from the code under
// test): the pinned date is Wed, Oct 7, 2026 (clock.ts, noon in Minneapolis); the
// counts are the sample data's (apps/api/app/testing/sample_data.py, 25 shows in its window;
// five on 2026-10-07, ids 8, 22, 23, 24, 25, per the B5 plan's fixture table and
// re-checked against lib/fixtures/shows.json).
test("the Today row is the pinned Wednesday", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("article")).toHaveCount(25);

  // Playwright's getByRole has no `current` option (that is Testing Library's), so find
  // the row by what a person sees, the "Today" badge, then assert the attribute a
  // screen reader gets.
  const today = page.getByRole("listitem").filter({ has: page.getByText("Today", { exact: true }) });
  await expect(today).toHaveCount(1);
  await expect(today).toHaveAttribute("aria-current", "date");
  await expect(today.getByRole("heading", { level: 2 })).toHaveText(/^Wed, Oct 7\s*Today$/);
  await expect(today.getByRole("article")).toHaveCount(5);
});
