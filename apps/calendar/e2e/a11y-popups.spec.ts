/**
 * Accessibility scans with a filter popup OPEN (B6 plan, Step 5).
 *
 * A scan of a page at rest never sees what a popup does to it. Opening the Venues
 * combobox makes Base UI mark the rest of the page `aria-hidden` while focusable
 * elements remain inside it (finding B6-F2), and a popup's own options have to meet
 * the same rules as the page. So each of the three popups is scanned open, against the
 * ratchet baseline. Desktop width only: the popups are the same component at every width.
 */
import { expectBaseline } from "./support/a11y";
import { POPUP_LABELS } from "./support/labels";
import { expect, test } from "./support/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("article")).toHaveCount(25);
});

// Proves: the Venues popup, open, has no accessibility violation beyond the baseline's.
// At the time of writing the baseline holds B6-F2 (`aria-hidden-focus`).
test("the Venues popup open has no new accessibility violations", async ({ page }) => {
  await page.getByLabel("Venues").click();
  await expect(page.getByRole("option").first()).toBeVisible();

  await expectBaseline(page, POPUP_LABELS.venues);
});

// Proves: the Artists popup with one option HIGHLIGHTED by the keyboard (ArrowDown) is
// accessible too: the highlighted state changes colours and sets `aria-activedescendant`,
// states a popup scanned without a highlight never sees.
test("the Artists popup open, an option highlighted, has no new accessibility violations", async ({
  page,
}) => {
  await page.getByLabel("Artists").click();
  await expect(page.getByRole("option").first()).toBeVisible();
  await page.keyboard.press("ArrowDown");

  await expectBaseline(page, POPUP_LABELS.artists);
});

// Proves: the Month select's popup, open, has no accessibility violation beyond the
// baseline's. It is a different Base UI component (a select, not a combobox), so it is
// checked separately.
test("the Month popup open has no new accessibility violations", async ({ page }) => {
  await page.getByLabel("Month").click();
  await expect(page.getByRole("option").first()).toBeVisible();

  await expectBaseline(page, POPUP_LABELS.month);
});
