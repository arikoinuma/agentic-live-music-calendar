/**
 * Journey J6a (B6 plan): reaching a venue page through a link on the calendar.
 */
import { expect, test } from "./support/test";

// Proves: a venue heading on the calendar is a real link to that venue's page, the
// page renders (an async Server Component, which Vitest cannot run), and it shows that
// venue's calendar. The link is scoped to the Oct 7 row by its date heading, because
// every date a venue plays has the same venue heading and a bare name would match
// several (strict mode would refuse it). Expected values: Zhora Darling is venue 3,
// plays Oct 7 (show 24), and has 6 shows in the window (lib/fixtures/shows.json).
test("a venue heading on the calendar leads to the venue page", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("article")).toHaveCount(25);

  const oct7 = page.getByRole("listitem").filter({ has: page.getByRole("link", { name: "Wed, Oct 7" }) });
  await oct7.getByRole("link", { name: "Zhora Darling" }).click();

  await expect(page).toHaveURL("/venue/3");
  await expect(page.getByRole("heading", { level: 1, name: "Zhora Darling" })).toBeVisible();
  await expect(page.getByRole("article")).toHaveCount(6);
});
