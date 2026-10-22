/**
 * Journey J6b (B6 plan): reaching an artist page through a link on the calendar.
 */
import { expect, test } from "./support/test";

// Proves: an artist name in a show block is a real link to that artist's page, and the
// page lists the artist's upcoming shows. The link is scoped to one show's block
// (found by its time link) because Beasthead plays several shows and a bare name
// would match each. Expected values: show 2 is Zhora Darling, Wed Sep 30, 9:00 PM to
// 11:30 PM, so its time link reads "9:00 PM – 11:30 PM" plus the hidden ", show details"
// (a real browser puts a space before that comma, so the name is matched with `\s*`); Beasthead is
// artist 9 and plays four shows (ids 2, 8, 11, 17) (lib/fixtures/shows.json).
test("an artist name in a show block leads to the artist page", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("article")).toHaveCount(25);

  const show2 = page
    .getByRole("article")
    .filter({ has: page.getByRole("link", { name: /^9:00 PM – 11:30 PM\s*, show details$/ }) });
  await show2.getByRole("link", { name: "Beasthead" }).click();

  await expect(page).toHaveURL("/artist/9");
  await expect(page.getByRole("heading", { level: 1, name: "Beasthead" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "Upcoming shows" })).toBeVisible();
  await expect(page.getByRole("article")).toHaveCount(4);
});
