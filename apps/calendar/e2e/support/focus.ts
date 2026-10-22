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
 * WCAG 2.4.11 (Focus Not Obscured, minimum, new in 2.2, B6-K2): a focused control must not
 * be ENTIRELY hidden by author-created content, here the sticky date headings
 * (requirements-initial.md: "not covered by sticky headers"). Playwright's `toBeVisible()`
 * and `toBeInViewport()` ignore overlap, so this asks the browser what is on top AT THE
 * CONTROL'S CENTRE. That is stricter than the criterion (a control whose centre is covered
 * but whose corner shows still passes 2.4.11): a sufficient check, not the definition; if it
 * ever goes red for a control that is partly visible, loosen it deliberately. Call it after
 * the Tab keypress has resolved, which is after the browser has scrolled the control into view.
 *
 * `getClientRects()[0]` is the first line box: a wrapped inline link's bounding-box centre
 * can fall between its lines and report a false "obscured".
 */
export async function isFocusObscured(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    const el = document.activeElement as HTMLElement;
    const r = el.getClientRects()[0] ?? el.getBoundingClientRect();
    const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return !(top && (top === el || el.contains(top)));
  });
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
 * (WCAG 1.4.11 asks 3:1 of the visual information that identifies a focused component.)
 * `area` is the box to photograph when it is not the focused element itself, such as the
 * wrapper that draws a combobox's ring while its inner input holds focus.
 *
 * Two guards keep a change nobody can see from counting as an indicator (code review round
 * 1 of B6 found the first version, "the strongest changed pixel against the page", crediting
 * both). Each changed pixel is scored by the LOWER of two contrasts: against the page
 * background (what WCAG 1.4.11 asks of an indicator) and against the pixel it replaced (what
 * makes the change visible at all). Text going from #000 to #222 is "high contrast" against a
 * white page but 1.1:1 against what it replaced, so it scores 1.1; a faint border turning
 * dark scores well on both. A floor on the second contrast alone ("visibly different,
 * then score against the page") was tried in the B6-F3 fix and was wrong: it credited a step
 * such as #000 to #444 (2.2:1 between the states, 9.7:1 against the page) as a strong
 * indicator (code review round 2, finding 2). And the result is the score that half an
 * outline's worth of pixels reaches (half of a one-pixel ring around the control's box): a speck
 * of a few maximum-contrast pixels outlines nothing and reads as 1:1. `changedPixels` is how
 * many pixels changed at all.
 */
export async function measureFocusIndicator(
  page: Page,
  target: Locator,
  area: Locator = target,
): Promise<{ changedPixels: number; ratio: number }> {
  await target.evaluate((el) => (el as HTMLElement).blur());
  await page.mouse.move(0, 0); // no hover: it would be a second thing that changes
  const { clip, box } = await clipAround(area, 8);

  const before = await readPixels(page, clip);
  await target.focus();
  const after = await readPixels(page, clip);

  const background: Pixel = [before.data[0]!, before.data[1]!, before.data[2]!];
  const scores: number[] = [];
  for (let i = 0; i < before.data.length; i += 4) {
    const was: Pixel = [before.data[i]!, before.data[i + 1]!, before.data[i + 2]!];
    const now: Pixel = [after.data[i]!, after.data[i + 1]!, after.data[i + 2]!];
    if (was[0] === now[0] && was[1] === now[1] && was[2] === now[2]) continue;
    scores.push(Math.min(contrastRatio(now, background), contrastRatio(now, was)));
  }

  // The least that could be called an indicator: HALF of a one-pixel ring around the
  // control's box (a full ring has 2 * (width + height) - 4 pixels). The gap that matters
  // is between a speck (a handful of pixels) and a ring (hundreds), so the bar sits well
  // inside it. A stricter bar was tried and was fragile: a real 1px border on a rounded box
  // paints only about 85% of its perimeter solidly (corners, sub-pixel edges), so 90% counted
  // or missed it by a few pixels. Half also still accepts an underline-style indicator.
  const outline = Math.ceil(0.5 * (2 * (box.width + box.height) - 4));
  scores.sort((a, b) => b - a);
  return { changedPixels: scores.length, ratio: scores.length >= outline ? scores[outline - 1]! : 1 };
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
