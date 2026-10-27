/**
 * Journey J5 (B6 plan): the day view's three orderings, switched with plain links.
 */
import { expect, test } from "./support/test";

// Expected values for 2026-10-07 (apps/api/app/testing/sample_data.py; lib/fixtures/shows.json):
// five shows. At White Squirrel 6:00 PM (Lanue) and 10:00 PM (Nooky Jones, Pert Near
// Sandstone); Zhora Darling 8:00 PM (Charlie Parr); The Terminal Bar 9:00 PM (Jaedyn
// James, Tarnation, Beasthead); The Midway Saloon at 1:00 AM, which is after midnight
// and so shown as the next day, "1:00 AM Thu" (requirements-initial.md, "Times after
// midnight"; B4). Eight artist rows in total.
const DAY = "/day/2026-10-07";

test.describe("the day view on Wed, Oct 7", () => {
  // Proves: the default ordering is by venue name and has ONE URL, the bare one (B4-D6:
  // a default must not also be reachable as `?sort=venue`). The current mode is marked
  // `aria-current="page"` and is not a link. Venues read alphabetically, a venue's own
  // shows by time.
  test("lists shows by venue, which is the default", async ({ page }) => {
    await page.goto(DAY);
    const nav = page.getByRole("navigation", { name: "Order shows" });

    await expect(nav.getByText("By venue")).toHaveAttribute("aria-current", "page");
    await expect(nav.getByRole("link", { name: "By venue" })).toHaveCount(0);
    await expect(page.getByRole("article")).toHaveCount(5);
    const order = await page.getByRole("article").allTextContents();
    const expected = [
      ["The Midway Saloon", "1:00 AM Thu"],
      ["The Terminal Bar", "9:00 PM"],
      ["The White Squirrel Bar", "6:00 PM"],
      ["The White Squirrel Bar", "10:00 PM"],
      ["Zhora Darling", "8:00 PM"],
    ];
    expected.forEach(([venue, time], i) => {
      expect(order[i]).toContain(venue);
      expect(order[i]).toContain(time);
    });
  });

  // Proves: "By time" is a link to `?sort=time`, switching to it changes the URL and the
  // order (earliest first, the after-midnight show last because it belongs to this
  // night), and the current mode moves to "By time". It is a plain link, so it works
  // before any JavaScript runs.
  test("switches to time order", async ({ page }) => {
    await page.goto(DAY);
    await page.getByRole("link", { name: "By time" }).click();

    await expect(page).toHaveURL(`${DAY}?sort=time`);
    const nav = page.getByRole("navigation", { name: "Order shows" });
    await expect(nav.getByText("By time")).toHaveAttribute("aria-current", "page");
    await expect(nav.getByRole("link", { name: "By venue" })).toBeVisible();
    await expect(page.getByRole("article")).toHaveCount(5);
    const order = await page.getByRole("article").allTextContents();
    const expected = [
      ["The White Squirrel Bar", "6:00 PM"],
      ["Zhora Darling", "8:00 PM"],
      ["The Terminal Bar", "9:00 PM"],
      ["The White Squirrel Bar", "10:00 PM"],
      ["The Midway Saloon", "1:00 AM Thu"],
    ];
    expected.forEach(([venue, time], i) => {
      expect(order[i]).toContain(venue);
      expect(order[i]).toContain(time);
    });
  });

  // Proves: "By artist" lists one row per artist on the night, alphabetically (eight
  // here), at `?sort=artist`; and "By venue" brings back the BARE URL, not `?sort=venue`.
  test("switches to artist order and back to the default", async ({ page }) => {
    await page.goto(DAY);
    await page.getByRole("link", { name: "By artist" }).click();

    await expect(page).toHaveURL(`${DAY}?sort=artist`);
    const rows = page.getByRole("main").getByRole("listitem");
    await expect(rows).toHaveCount(8);
    await expect(rows.first()).toContainText("Beasthead");
    await expect(rows.last()).toContainText("Tarnation");

    await page.getByRole("link", { name: "By venue" }).click();
    await expect(page).toHaveURL(DAY);
  });
});
