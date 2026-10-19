/**
 * Journey J3 (B6 plan): a filter that matches nothing, and the way back.
 */
import { expect, test } from "./support/test";

// Proves: a combination with no shows ends in the "No matches found." state with a
// working reset link, end to end. B5 could test that message only on a hand-built
// component; here it is reached the way a visitor reaches it, through two comboboxes,
// and the reset link really restores the whole calendar. Expected values: Charlie
// Parr (artist 1) plays only venues 1 and 3 (lib/fixtures/shows.json), so The
// Midway Saloon (venue 2) with Charlie Parr has no shows; the unfiltered calendar
// has 25.
test("a filter with no matches shows the empty state, and Reset filters restores the calendar", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByRole("article")).toHaveCount(25);

  await page.getByLabel("Venues").click();
  await page.getByRole("option", { name: "The Midway Saloon" }).click();
  await page.keyboard.press("Escape");
  await page.getByLabel("Artists").click();
  await page.getByRole("option", { name: "Charlie Parr" }).click();
  await page.keyboard.press("Escape");

  await expect(page).toHaveURL("/?venue=2&artist=1");
  await expect(page.getByText("No matches found.")).toBeVisible();
  await expect(page.getByRole("article")).toHaveCount(0);

  const reset = page.getByRole("link", { name: "Reset filters" });
  await expect(reset).toHaveAttribute("href", "/");
  await reset.click();

  await expect(page).toHaveURL("/");
  await expect(page.getByRole("article")).toHaveCount(25);
});
