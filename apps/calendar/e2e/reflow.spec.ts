/**
 * Reflow at phone widths (WCAG 2.2 success criterion 1.4.10; B6 plan, Step 6 and B6-D6).
 */
import { expectNoPageReflow } from "./support/reflow";
import { SCREENS } from "./support/screens";
import { test } from "./support/test";

// 320 is the criterion's own width (a 1280px window at 400% zoom); 375 is a common phone.
const WIDTHS = [320, 375];

for (const width of WIDTHS) {
  for (const screen of SCREENS) {
    // Proves: on this screen, at this width, the PAGE does not scroll sideways. The venue
    // rows inside the calendar scroll sideways on purpose within their own regions
    // (decision B6-D6, treated as the criterion's two-dimensional-content exception), so
    // only the page itself is held to this. Fails if any element (a wide table, a long
    // unbroken URL, a fixed-width block) pushes the page wider than the screen.
    test(`${screen.path} does not scroll the page sideways @${width}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 });
      await page.goto(screen.path);
      await screen.ready(page);

      await expectNoPageReflow(page);
    });
  }
}
