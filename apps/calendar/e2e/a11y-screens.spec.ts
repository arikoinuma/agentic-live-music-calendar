/**
 * Accessibility scan of EVERY screen, at desktop and phone width (B6 plan, Step 5).
 *
 * The requirement is "every screen meets WCAG 2.2 AA" (requirements-initial.md), so
 * one test per screen per width, each held to the ratchet baseline
 * (e2e/support/a11y-baseline.ts). Each test also asserts the page's exact browser
 * title (WCAG 2.4.2, Page Titled), since the page is already loaded and the title is
 * cheap to check.
 *
 * The screens, and where their expected titles come from, are in support/screens.ts.
 */
import { expectBaseline } from "./support/a11y";
import { SCREENS, SITE, WIDTHS } from "./support/screens";
import { expect, test } from "./support/test";

for (const width of WIDTHS) {
  for (const screen of SCREENS) {
    // Proves: this screen, at this width, has no accessibility violation beyond the
    // baseline's (a new one fails; so does a fixed one the baseline still lists), and
    // its browser title is the exact expected text.
    test(`${screen.path} has no new accessibility violations @${width}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 });
      await page.goto(screen.path);
      await screen.ready(page);

      await expect(page).toHaveTitle(screen.title);
      await expectBaseline(page, `${screen.path} @${width}`);
    });
  }

  // Proves: the error screen (what a visitor sees when the API is down) is accessible
  // too. The delay proxy answers 502 to everything, the home page's body throws, and
  // after hydration the app's error boundary takes over its region (app/error.tsx).
  // The title stays the site's.
  test(`the error screen has no new accessibility violations @${width}`, async ({ page, stack }) => {
    await stack.fail();
    await page.setViewportSize({ width, height: 800 });
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1, name: "Something went wrong" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();

    await expect(page).toHaveTitle(SITE);
    await expectBaseline(page, `/ (API down) @${width}`);
  });
}
