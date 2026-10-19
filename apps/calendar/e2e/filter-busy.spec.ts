/**
 * Journey J8 (B6 plan): the busy state while a filter change is in flight.
 */
import { expect, test } from "./support/test";

// Proves: while a pick is being answered, the header says so and the choice is
// already on screen. `aria-busy="true"` is set, the status reads "Updating…", and the
// chip is there at once (the optimistic value); when the page settles, `aria-busy`
// becomes the STRING "false" (it is not removed), the status empties and the calendar
// is the venue's. Against a fast API all of this lasts a few milliseconds, which is why
// B5's mocked-router tests could not see it (B5 fact 12); the delay proxy slows the API
// to 1.5 s. `aria-busy` is located by its attribute because it sits on a plain div with
// no role: it is an ARIA state, which is what assistive technology reads, not styling.
// Expected values: venue 1 has 8 of the 25 shows (lib/fixtures/shows.json).
test("a filter change shows the busy state, then settles", async ({ page, stack }) => {
  await page.goto("/");
  await expect(page.getByRole("article")).toHaveCount(25);
  await stack.delay(1500);

  await page.getByLabel("Venues").click();
  await page.getByRole("option", { name: "The White Squirrel Bar" }).click();
  await page.keyboard.press("Escape"); // the open popup hides the page from role queries (finding B6-F2)

  // In flight: busy, "Updating…", and the choice already shown.
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(1);
  await expect(page.getByText("Updating…")).toBeVisible();
  await expect(page.getByRole("button", { name: "Remove The White Squirrel Bar" })).toBeVisible();

  // Settled.
  await expect(page.getByRole("article")).toHaveCount(8);
  await expect(page.locator('[aria-busy="false"]')).toHaveCount(1);
  await expect(page.getByText("Updating…")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Remove The White Squirrel Bar" })).toBeVisible();
});
