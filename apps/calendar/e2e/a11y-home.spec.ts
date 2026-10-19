/**
 * Accessibility scan of the home page (B6 plan, Step 3): axe with the WCAG 2.2 AA
 * rule sets, held to the ratchet baseline. The other screens, the popup states and
 * the custom checks axe cannot make follow in later steps.
 */
import { expectBaseline } from "./support/a11y";
import { expect, test } from "./support/test";

// Proves: the home page has no accessibility violation beyond the known ones in
// e2e/support/a11y-baseline.ts. A NEW violation (an unlabelled control, a low-contrast
// text, a too-small target) makes this fail, and so does fixing a known one without
// updating the baseline (the ratchet only turns one way). The scan waits for all 25
// shows first so it sees the calendar and not the loading skeleton.
test("the home page has no new accessibility violations", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("article")).toHaveCount(25);

  await expectBaseline(page, "/ @1280");
});
