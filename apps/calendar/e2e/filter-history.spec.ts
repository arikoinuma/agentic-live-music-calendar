/**
 * Journey J4 (B6 plan; added, not in the build plan): the Back button after a filter.
 */
import { expect, test } from "./support/test";

// Proves: Back undoes a filter change. Picking a venue PUSHES a history entry (B3-D8:
// `push`, not `replace`), so Back returns to the unfiltered calendar with the chip
// gone. This is the one history behaviour jsdom cannot show (its router is mocked).
// A change to `replace` would pass every unit test and make Back leave the site.
// Expected values: the unfiltered calendar has 25 shows (the sample window).
test("Back after picking a venue returns to the unfiltered calendar", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("article")).toHaveCount(25);

  await page.getByLabel("Venues").click();
  await page.getByRole("option", { name: "The White Squirrel Bar" }).click();
  await expect(page).toHaveURL("/?venue=1");
  // A multi-select's popup stays open after a pick, and while it is open Base UI marks
  // the rest of the page aria-hidden (the same behaviour as finding B6-F2). Role queries
  // then cannot see the calendar behind it, so close it before asserting on the page.
  await page.keyboard.press("Escape");

  await page.goBack();

  await expect(page).toHaveURL("/");
  await expect(page.getByRole("button", { name: "Remove The White Squirrel Bar" })).toHaveCount(0);
  await expect(page.getByRole("article")).toHaveCount(25);
});
