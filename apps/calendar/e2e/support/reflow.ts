/**
 * Reflow (WCAG 2.2, success criterion 1.4.10): the page must not need sideways scrolling.
 */
import type { Page } from "@playwright/test";

/**
 * Assert that the PAGE does not scroll sideways at the viewport's current width.
 *
 * TODO(Ari) — Lesson: WCAG 1.4.10 (Reflow): at 320 CSS pixels wide (the width of a
 *   1280px window at 400% zoom) the PAGE must not need a horizontal scrollbar. The venue
 *   rows scroll sideways ON PURPOSE, inside their own regions (B6 plan, D6), so this
 *   measures the DOCUMENT, not `body` (which `overflow-x: hidden` can hide) and not the
 *   scrollers. Set the viewport BEFORE navigating, so the layout is computed at that width
 *   (the spec does).
 * Code:
 *   const { w, c } = await page.evaluate(() => ({
 *     w: document.documentElement.scrollWidth,
 *     c: document.documentElement.clientWidth,
 *   }));
 *   expect(w).toBeLessThanOrEqual(c);
 *   (and `import { expect } from "./test";` at the top)
 * Check: `pnpm --filter calendar exec playwright test e2e/reflow.spec.ts`: 30 tests, red
 *   until this is written, green on the real pages (plan prototype: width equals the
 *   viewport on every route at 320 and 375). Likeliest mistake: `document.body.scrollWidth`.
 */
export async function expectNoPageReflow(page: Page): Promise<void> {
  void page;
  throw new Error("TODO(Ari)");
}
