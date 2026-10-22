/**
 * Journey J2 (B6 plan): filtering the calendar by venue through the real combobox.
 */
import { expect, test } from "./support/test";

// Proves: picking a venue in the Venues combobox does the whole round trip in a
// real browser. The client component pushes the new URL through the real router, the
// server page re-renders from that URL, and the calendar shrinks to that venue's
// shows. The URL is asserted WHOLE (`/?venue=1`, the one canonical form), the chip
// is found by the accessible name of its remove button (the B5-D3 fix: a screen
// reader hears "Remove The White Squirrel Bar", not "button"), and the count is the
// venue's. jsdom could show the pushed URL (B5) but not the server answering it.
// Expected values: venue 1 is The White Squirrel Bar and has 8 of the 25 shows in
// the window (lib/fixtures/venues.json and shows.json; B5 plan, fact 13).
test("picking a venue filters the calendar and the URL", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("article")).toHaveCount(25);

  await page.getByLabel("Venues").click();
  await page.getByRole("option", { name: "The White Squirrel Bar" }).click();
  // A multi-select's popup stays open after a pick, and while it is open Base UI marks
  // the rest of the page aria-hidden (the same behaviour as finding B6-F2). Role queries
  // then cannot see the calendar behind it, so close it before asserting on the page.
  await page.keyboard.press("Escape");

  await expect(page).toHaveURL("/?venue=1");
  await expect(page.getByRole("button", { name: "Remove The White Squirrel Bar" })).toBeVisible();
  await expect(page.getByRole("article")).toHaveCount(8);
});
