/**
 * The accessibility ratchet's data and comparison (B6 plan, "The ratchet", D5).
 *
 * A FINDING is one row: how many elements on one page break one rule. The BASELINE
 * is the committed list of findings we already know about, each tied to the
 * `B6-F<n>` entry in the plan's findings table. A scan must match it exactly:
 *
 *   - worse than the baseline (a new rule, or more elements) is "added": a new problem;
 *   - better than the baseline (a row gone, or fewer elements) is "stale": a fix that
 *     the baseline has not caught up with.
 *
 * Both fail the test. Failing on "stale" is the point: deleting a row IS the red
 * step of a fix (the test fails until the baseline records it), and a rule that was
 * fixed cannot quietly come back, because its row is gone and a return shows as "added".
 *
 * This file is pure data and logic, so `a11y-baseline.test.ts` can test it without a
 * browser. Scanning lives in `a11y.ts`.
 */

/** One page, one rule, how many elements. `page` is a label such as "/ @1280" (URL and viewport width). */
export type Finding = { page: string; ruleId: string; nodes: number };

/** A baseline row also names the finding in the plan's table that it belongs to. */
export type BaselineEntry = Finding & { finding: string };

/**
 * Compare a scan's findings with the baseline rows for the same page(s).
 * Returns what is worse than the baseline (`added`) and what is better (`stale`),
 * each as `[ruleId@page, element count]` pairs. Both empty means an exact match.
 */
export function compareToBaseline(
  found: Finding[],
  baseline: Finding[],
): { added: [string, number][]; stale: [string, number][] } {
  const key = (e: Finding) => `${e.ruleId}@${e.page}`;
  const known = new Map(baseline.map((e) => [key(e), e.nodes]));
  const seen = new Map(found.map((e) => [key(e), e.nodes]));
  return {
    added: [...seen].filter(([k, n]) => (known.get(k) ?? 0) < n), // new, or more elements than known
    stale: [...known].filter(([k, n]) => (seen.get(k) ?? 0) < n), // fixed, or fewer elements than known
  };
}

/**
 * The known findings. Rows are added when a scan first finds a problem (and Ari has
 * seen it), and deleted when its fix lands. Each `finding` is an ID in the plan's
 * findings table (docs/dev/implementations/b6-accessibility-and-e2e.md).
 */
export const BASELINE: BaselineEntry[] = [
  // B6-F1: artist links in show blocks are 18px high; WCAG 2.5.8 (Target Size, minimum)
  // wants 24. First found by the home-page scan, Step 3.
  { page: "/ @1280", ruleId: "target-size", nodes: 6, finding: "B6-F1" },
  // The same links on the other screens that list artists, at both widths (Step 5).
  { page: "/ @375", ruleId: "target-size", nodes: 6, finding: "B6-F1" },
  { page: "/day/2026-10-07 @1280", ruleId: "target-size", nodes: 2, finding: "B6-F1" },
  { page: "/day/2026-10-07 @375", ruleId: "target-size", nodes: 2, finding: "B6-F1" },
  { page: "/day/2026-10-07?sort=time @1280", ruleId: "target-size", nodes: 2, finding: "B6-F1" },
  { page: "/day/2026-10-07?sort=time @375", ruleId: "target-size", nodes: 2, finding: "B6-F1" },
  { page: "/artist/1 @1280", ruleId: "target-size", nodes: 2, finding: "B6-F1" },
  { page: "/artist/1 @375", ruleId: "target-size", nodes: 2, finding: "B6-F1" },
  // With a popup open (Step 5). The Month popup leaves the page readable, so F1 shows
  // through; the two combobox popups mark the rest of the page aria-hidden instead (F2).
  { page: "/ venues popup open @1280", ruleId: "aria-hidden-focus", nodes: 5, finding: "B6-F2" },
  { page: "/ artists popup open, option highlighted @1280", ruleId: "aria-hidden-focus", nodes: 5, finding: "B6-F2" },
  { page: "/ month popup open @1280", ruleId: "target-size", nodes: 6, finding: "B6-F1" },
];
