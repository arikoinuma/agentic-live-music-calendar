/**
 * Journey J6c (B6 plan): reaching a show's own page through its time link.
 */
import { expect, test } from "./support/test";

// Proves: a show block's time line is a link to that show's page, and the page names
// the show: heading, lineup section, and a browser title written from B4-D7's format
// (`<artists> at <venue>, <weekday, month day, year>`, then the layout's
// `· Agentic Live Music Calendar` suffix). The title is written out here from that
// format and the sample data (show 2: Nooky Jones then Beasthead, at Zhora Darling,
// Wed, Sep 30, 2026), never copied from what the page printed.
test("a show's time link leads to the show page", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("article")).toHaveCount(25);

  await page.getByRole("link", { name: /^9:00 PM – 11:30 PM\s*, show details$/ }).click();

  await expect(page).toHaveURL("/show/2");
  await expect(page.getByRole("heading", { level: 1, name: "Nooky Jones, Beasthead" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "Lineup" })).toBeVisible();
  await expect(page).toHaveTitle(
    "Nooky Jones, Beasthead at Zhora Darling, Wed, Sep 30, 2026 · Agentic Live Music Calendar",
  );
});
