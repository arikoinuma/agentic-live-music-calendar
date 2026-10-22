/**
 * The WCAG contrast ratio between two sRGB colours (WCAG 2.2, "contrast ratio" and
 * "relative luminance"). Used to judge painted focus indicators and control borders
 * (success criterion 1.4.11, which asks 3:1) and, in principle, text (1.4.3).
 */

/** Red, green, blue, each 0 to 255. */
export type Rgb = [number, number, number];

/** One channel, converted from the gamma-encoded sRGB value a screenshot holds to linear light. */
function linear(channel: number): number {
  const c = channel / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

/** How bright a colour is to the eye, 0 (black) to 1 (white); green counts most, blue least. */
function luminance([r, g, b]: Rgb): number {
  return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b);
}

/** (lighter + 0.05) / (darker + 0.05): 1 for identical colours, 21 for black on white. Order does not matter. */
export function contrastRatio(a: Rgb, b: Rgb): number {
  const [lighter, darker] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (lighter + 0.05) / (darker + 0.05);
}
