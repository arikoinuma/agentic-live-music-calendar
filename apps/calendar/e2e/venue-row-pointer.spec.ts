/**
 * Pressing or tapping a link that sits partly outside a venue row's visible area
 * (B6 plan, code review round 2, finding 1).
 *
 * `ScrollRow` (the sideways-scrolling venue row) scrolls the focused control's column into
 * view so KEYBOARD users can see where focus is (finding B6-F7). A mouse press or a tap also
 * focuses a link, and if the row scrolled then, it would move the link out from under the
 * pointer between press and release, and the click would land on something else.
 */
import { expect, test } from "./support/test";

// The pointer is pressed on the visible part of show 2's time link at 375px: the link spans
// x 297-425 and the row's visible area ends at x 359, so its left part is on screen. Expected
// value: the click opens show 2's page, `/show/2` (apps/api sample data, B5's fixture table).
// The raw mouse/touch coordinates are deliberate: a Locator click would first scroll the link
// into view itself, which is exactly the situation being tested.
const SHOW_2_TIME = /^9:00 PM – 11:30 PM\s*, show details$/;
// Tall on purpose: at 700px high show 2 sits below the fold (y about 794), and a press below the
// viewport reaches nothing, which would make this journey red for the wrong reason.
const VIEWPORT = { width: 375, height: 1200 };

// Proves: a mouse click on the visible part of a partly visible link follows the link. Fails
// if focusing the link scrolls the row before the click completes (the first version of
// ScrollRow did: the click landed elsewhere and the URL stayed `/`).
test("a mouse click on a partly visible link opens it", async ({ page }) => {
  await page.setViewportSize(VIEWPORT);
  await page.goto("/");
  await expect(page.getByRole("article")).toHaveCount(25);

  const box = (await page.getByRole("link", { name: SHOW_2_TIME }).boundingBox())!;
  expect(box.x + 20, "the point pressed is on screen and left of the row's edge").toBeLessThan(359);
  expect(box.y + box.height, "the link is within the first screen").toBeLessThan(VIEWPORT.height);
  await page.mouse.click(box.x + 20, box.y + box.height / 2);

  await expect(page).toHaveURL("/show/2");
});

test.describe("on a touch screen", () => {
  test.use({ hasTouch: true });

  // Proves: the same for a tap, which is how a phone user presses the same link. (Chrome on a
  // phone focuses a tapped link; Safari on iOS does not, so it is probably unaffected there.)
  test("a tap on a partly visible link opens it", async ({ page }) => {
    await page.setViewportSize(VIEWPORT);
    await page.goto("/");
    await expect(page.getByRole("article")).toHaveCount(25);

    const box = (await page.getByRole("link", { name: SHOW_2_TIME }).boundingBox())!;
    await page.touchscreen.tap(box.x + 20, box.y + box.height / 2);

    await expect(page).toHaveURL("/show/2");
  });
});
