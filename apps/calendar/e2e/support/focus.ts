/**
 * Keyboard focus checks that axe cannot make (B6 plan, Step 6).
 *
 * Two questions about focus: is the focused control hidden behind something
 * (`isFocusObscured`, WCAG 2.4.11), and how visible is the ring the browser paints
 * around it (`measureFocusIndicator`, WCAG 1.4.11)?
 */
import type { Locator, Page } from "@playwright/test";
import { contrastRatio, type Rgb } from "./contrast";

/**
 * Is the element that currently has keyboard focus covered at its centre by something else?
 *
 * TODO(Ari) — Lesson: WCAG 2.4.11 (Focus Not Obscured, minimum, new in 2.2): a focused
 *   control must not be ENTIRELY hidden by author-created content, here the sticky date
 *   headings (requirements-initial.md: "not covered by sticky headers"). Playwright's
 *   `toBeVisible()` and `toBeInViewport()` ignore overlap, so ask the browser what is on
 *   top AT THE CONTROL'S CENTRE. That is stricter than the criterion (a control whose
 *   centre is covered but whose corner shows still passes 2.4.11): a sufficient check, not
 *   the definition; if it ever goes red at 375px for a control that is partly visible, Ari
 *   decides whether to loosen it. Read it after the Tab keypress has resolved, which is
 *   after the browser has scrolled the control into view.
 * Code:
 *   return page.evaluate(() => {
 *     const el = document.activeElement as HTMLElement;
 *     const r = el.getClientRects()[0] ?? el.getBoundingClientRect();
 *     const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
 *     return !(top && (top === el || el.contains(top)));
 *   });
 *   `getClientRects()[0]` is the first line box: a wrapped inline link's bounding-box centre
 *   can fall between its lines and report a false "obscured".
 * Check: `pnpm --filter calendar exec playwright test e2e/keyboard.spec.ts -g "sticky"`: 4
 *   tests, red until this is written, green on the real pages WITH the baseline row for
 *   B6-F7: written strictly as above, one stop on `/` at 375px is reported (a link half cut
 *   off by its row's scroll container, not a sticky heading; the plan's worktree check found
 *   exactly that), and the baseline already lists it. Likeliest mistakes:
 *   `toBeVisible()`; accepting `top.contains(el)` (a covering ANCESTOR then passes).
 */
export async function isFocusObscured(page: Page): Promise<boolean> {
  void page;
  throw new Error("TODO(Ari)");
}

/** A colour read from a screenshot: what is painted, not what the CSS says. */
type Pixel = Rgb;

/**
 * Screenshot a clip of the page and return its pixels, decoded in the BROWSER (the PNG is
 * drawn onto a canvas and read back), so no image library is needed in Node.
 * `rows` is every pixel as a flat [r, g, b, a, r, g, b, a, …] list with the clip's width.
 */
async function readPixels(
  page: Page,
  clip: { x: number; y: number; width: number; height: number },
): Promise<{ width: number; data: number[] }> {
  // `animations: "disabled"` finishes CSS transitions first: the controls fade their border
  // in (`transition-colors`), and a screenshot taken mid-fade measures a half-painted ring.
  const png = (await page.screenshot({ clip, animations: "disabled" })).toString("base64");
  return page.evaluate(async (b64) => {
    const img = new Image();
    img.src = `data:image/png;base64,${b64}`;
    await img.decode();
    const canvas = document.createElement("canvas");
    canvas.width = img.width;
    canvas.height = img.height;
    const ctx = canvas.getContext("2d")!;
    ctx.drawImage(img, 0, 0);
    return { width: img.width, data: Array.from(ctx.getImageData(0, 0, img.width, img.height).data) };
  }, png);
}

/** The clip around an element, with room for a ring painted outside its box. */
async function clipAround(area: Locator, pad: number) {
  await area.scrollIntoViewIfNeeded();
  const box = (await area.boundingBox())!;
  const x = Math.max(0, box.x - pad);
  const y = Math.max(0, box.y - pad);
  return { clip: { x, y, width: box.width + 2 * pad + (box.x - pad - x), height: box.height + 2 * pad + (box.y - pad - y) }, box, x, y };
}

/**
 * How visible is the focus indicator the browser actually paints for `target`?
 *
 * The indicator is the set of pixels that CHANGE between a screenshot taken before and one
 * taken after focusing the control: exactly what focus adds, whether a ring, an outline or a
 * border colour, and nothing else (the control's own text and underline are in both shots).
 * The result is the strongest contrast, against the page background, of any pixel it added.
 * (WCAG 1.4.11 asks 3:1 of the visual information that identifies a focused component.)
 * `area` is the box to photograph when it is not the focused element itself, such as the
 * wrapper that draws a combobox's ring while its inner input holds focus.
 */
export async function measureFocusIndicator(
  page: Page,
  target: Locator,
  area: Locator = target,
): Promise<{ changedPixels: number; ratio: number }> {
  await target.evaluate((el) => (el as HTMLElement).blur());
  await page.mouse.move(0, 0); // no hover: it would be a second thing that changes
  const { clip } = await clipAround(area, 8);

  const before = await readPixels(page, clip);
  await target.focus();
  const after = await readPixels(page, clip);

  const background: Pixel = [before.data[0]!, before.data[1]!, before.data[2]!];
  let changedPixels = 0;
  let ratio = 1;
  for (let i = 0; i < before.data.length; i += 4) {
    const same =
      before.data[i] === after.data[i] &&
      before.data[i + 1] === after.data[i + 1] &&
      before.data[i + 2] === after.data[i + 2];
    if (same) continue;
    changedPixels++;
    ratio = Math.max(ratio, contrastRatio([after.data[i]!, after.data[i + 1]!, after.data[i + 2]!], background));
  }
  return { changedPixels, ratio };
}

/**
 * How visible is a control's own boundary when it is NOT focused?
 *
 * Takes the strongest contrast, against the page background, of any pixel within two pixels
 * of the control's edge (the border). WCAG 1.4.11 asks 3:1 of the boundary that identifies a
 * control when nothing else (a label, an icon) does.
 */
export async function measureControlBorder(page: Page, control: Locator): Promise<number> {
  await control.evaluate((el) => (el as HTMLElement).blur());
  await page.mouse.move(0, 0);
  const { clip, box, x, y } = await clipAround(control, 8);
  const pixels = await readPixels(page, clip);

  const background: Pixel = [pixels.data[0]!, pixels.data[1]!, pixels.data[2]!];
  const height = pixels.data.length / 4 / pixels.width;
  // The control's edge, in the clip's own coordinates.
  const left = box.x - x;
  const top = box.y - y;
  const right = left + box.width;
  const bottom = top + box.height;
  let ratio = 1;
  for (let py = 0; py < height; py++) {
    for (let px = 0; px < pixels.width; px++) {
      const nearEdge =
        Math.min(Math.abs(px - left), Math.abs(px - right), Math.abs(py - top), Math.abs(py - bottom)) <= 2 &&
        px >= left - 2 &&
        px <= right + 2 &&
        py >= top - 2 &&
        py <= bottom + 2;
      if (!nearEdge) continue;
      const i = (py * pixels.width + px) * 4;
      ratio = Math.max(ratio, contrastRatio([pixels.data[i]!, pixels.data[i + 1]!, pixels.data[i + 2]!], background));
    }
  }
  return ratio;
}
