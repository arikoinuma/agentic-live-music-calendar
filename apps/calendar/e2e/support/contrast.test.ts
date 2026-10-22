/**
 * The WCAG contrast ratio, as pure arithmetic (B6 plan, Step 6).
 *
 * The painted focus indicators and control borders are measured from screenshot pixels
 * in the browser (focus.ts); this is the arithmetic that turns two pixel colours into the
 * number WCAG 1.4.11 and 1.4.3 ask about. No browser needed.
 *
 * Where the expected values come from: the WCAG 2.2 definition of "contrast ratio"
 * ((L1 + 0.05) / (L2 + 0.05), L being relative luminance) and its published examples.
 * Black on white is the maximum, 21:1. White on white is the minimum, 1:1. Grey #777777 on
 * white is the textbook just-fails-AA example (4.48:1, under 4.5), and #767676 is the
 * lightest grey that passes (4.54:1). None is computed by the code under test.
 */
import { describe, expect, it } from "vitest";
import { contrastRatio, type Rgb } from "./contrast";

const WHITE: Rgb = [255, 255, 255];
const BLACK: Rgb = [0, 0, 0];

describe("contrastRatio", () => {
  // Proves: the extremes. A formula with the wrong constants or the wrong sRGB curve
  // would miss 21 even if its middle values looked plausible.
  it("is 21:1 for black on white and 1:1 for a colour on itself", () => {
    expect(contrastRatio(BLACK, WHITE)).toBeCloseTo(21, 5);
    expect(contrastRatio(WHITE, WHITE)).toBeCloseTo(1, 5);
  });

  // Proves: the order of the two colours does not matter. Callers pass (indicator,
  // background) in whichever order is handy; the ratio is always lighter over darker.
  it("is the same whichever colour is passed first", () => {
    expect(contrastRatio(BLACK, WHITE)).toBe(contrastRatio(WHITE, BLACK));
  });

  // Proves: the sRGB-to-luminance curve is right at the two published boundary greys.
  // #777777 must come out under 4.5 and #767676 over it: a straight-line (non-gamma)
  // luminance would put both on the same side.
  it("matches the published grey-on-white boundary", () => {
    expect(contrastRatio([0x77, 0x77, 0x77], WHITE)).toBeCloseTo(4.48, 2);
    expect(contrastRatio([0x76, 0x76, 0x76], WHITE)).toBeCloseTo(4.54, 2);
  });
});
