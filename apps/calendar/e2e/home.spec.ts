/**
 * Journey J1 (B6 plan, "Browser tests"): the home page, loaded through a real
 * browser, a real Next server and the real API.
 *
 * Step 1 of the plan is ONE green test; this is it. Later steps extend it
 * (the pinned Today row, Step 2) and add the other journeys beside it.
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
