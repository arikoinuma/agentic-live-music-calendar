/**
 * Scanning a page with axe and holding the result to the baseline (B6 plan, Step 3).
 *
 * axe is the accessibility engine behind Lighthouse's audit, here run inside the
 * test's own browser on the page as it stands. It reports three buckets:
 * VIOLATIONS (a rule failed), PASSES, and INCOMPLETE (it could not decide, for
 * example when one element partly covers another and the colour behind text is
 * unknowable). Only violations are held to the baseline; incomplete results are
 * attached to the test report and triaged by hand (plan P13).
 */
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { BASELINE, compareToBaseline, type Finding } from "./a11y-baseline";
import { expect, test } from "./test";

/**
 * The rule sets WCAG 2.2 Level AA is made of: A and AA of 2.0, the 2.1 additions, and
 * the 2.2 additions (`wcag22aa`: target size). One constant so every scan uses the
 * same standard (B6 plan, "WCAG 2.2 AA coverage matrix").
 */
export const AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

/**
 * Scan the current page and require that its violations match the baseline rows for
 * `label` exactly. `label` is the page and viewport, e.g. "/ @1280"; it keys the
 * baseline rows. Wait for the page's real content BEFORE calling this, or the scan
 * sees the loading skeleton instead of the calendar.
 */
export async function expectBaseline(page: Page, label: string): Promise<void> {
  const result = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze();

  // Keep the full result with the test report: every violated rule, its help text and
  // each offending element, for whoever has to fix it.
  await test.info().attach(`axe violations: ${label}`, {
    body: JSON.stringify(result.violations, null, 2),
    contentType: "application/json",
  });
  // The cases axe could not decide: not failed, but never silently dropped.
  if (result.incomplete.length > 0) {
    await test.info().attach(`axe incomplete: ${label}`, {
      body: JSON.stringify(result.incomplete, null, 2),
      contentType: "application/json",
    });
  }

  const found: Finding[] = result.violations.map((v) => ({
    page: label,
    ruleId: v.id,
    nodes: v.nodes.length,
  }));
  const { added, stale } = compareToBaseline(
    found,
    BASELINE.filter((entry) => entry.page === label),
  );

  // Two assertions so the failure says which kind it is. "added" is a new problem to
  // fix; "stale" is a fix to record by lowering or deleting the baseline row.
  expect(
    added,
    `${label}: accessibility violations NOT in the baseline (new, or more elements than known) [rule@page, elements]`,
  ).toEqual([]);
  expect(
    stale,
    `${label}: baseline rows the page no longer matches (fixed, or fewer elements): lower or delete them in e2e/support/a11y-baseline.ts [rule@page, baseline elements]`,
  ).toEqual([]);
}
