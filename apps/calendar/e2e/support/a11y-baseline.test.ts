/**
 * The ratchet's comparison (B6 plan, "The ratchet" and B6-D5), with no browser.
 *
 * A "finding" is one row: how many elements on one page break one accessibility
 * rule. The baseline is the committed list of rows we already know about, and a
 * scan must match it EXACTLY: worse than the baseline is "added", better is
 * "stale", and both fail, so the list can shrink and never grow back.
 *
 * Where the expected values come from: every finding below is hand-made for the
 * case it names. None is read from `compareToBaseline` or from a real scan, so a
 * bug in the comparison cannot hide behind its own output.
 */
import { describe, expect, it } from "vitest";
import { BASELINE, compareToBaseline, type Finding } from "./a11y-baseline";
import { ALL_LABELS } from "./labels";

const row = (page: string, ruleId: string, nodes: number): Finding => ({ page, ruleId, nodes });

describe("compareToBaseline", () => {
  const baseline = [row("/ @1280", "target-size", 6)];

  // Proves: an unchanged page passes. The scan finds exactly what the baseline
  // lists, so nothing is added and nothing is stale. Without this a ratchet that
  // always complains would pass every "does it catch X" test below.
  it("reports nothing when the scan matches the baseline", () => {
    expect(compareToBaseline([row("/ @1280", "target-size", 6)], baseline)).toEqual({
      added: [],
      stale: [],
    });
  });

  // Proves: a brand-new rule is "added". This is the whole point of "fail on a new
  // violation": the scan found a problem the baseline does not know.
  it("reports a rule that is not in the baseline as added", () => {
    const found = [row("/ @1280", "target-size", 6), row("/ @1280", "button-name", 1)];
    expect(compareToBaseline(found, baseline)).toEqual({
      added: [["button-name@/ @1280", 1]],
      stale: [],
    });
  });

  // Proves: MORE elements than the baseline lists is "added", even for a known
  // rule. Without node counts a rule could grow from 6 elements to 60 and still
  // count as "known".
  it("reports more elements than the baseline lists as added", () => {
    expect(compareToBaseline([row("/ @1280", "target-size", 7)], baseline)).toEqual({
      added: [["target-size@/ @1280", 7]],
      stale: [],
    });
  });

  // Proves: a baseline row whose problem is gone is "stale", and that fails too.
  // This is the half many baseline tools omit: the fix must be recorded by
  // deleting the row, which is what turns each fix into a red-then-green step.
  it("reports a baseline row the scan no longer finds as stale", () => {
    expect(compareToBaseline([], baseline)).toEqual({
      added: [],
      stale: [["target-size@/ @1280", 6]],
    });
  });

  // Proves: FEWER elements than the baseline lists is "stale". Two of six links fixed
  // must lower the row to four; otherwise two new violations could later land in the
  // freed room, still "no more than six", and go unnoticed.
  it("reports fewer elements than the baseline lists as stale", () => {
    expect(compareToBaseline([row("/ @1280", "target-size", 4)], baseline)).toEqual({
      added: [],
      stale: [["target-size@/ @1280", 6]],
    });
  });

  // Proves: the same rule on two pages is two independent rows. A fix on `/` must
  // not be masked by the same rule still failing on `/day/...`, and vice versa.
  it("keeps the same rule on different pages independent", () => {
    const base = [row("/ @1280", "target-size", 6), row("/venue/1 @1280", "target-size", 2)];
    const found = [row("/ @1280", "target-size", 3), row("/venue/1 @1280", "target-size", 2)];
    expect(compareToBaseline(found, base)).toEqual({
      added: [],
      stale: [["target-size@/ @1280", 6]],
    });
  });

  // Proves: one scan can be better in one place and worse in another, and both are
  // reported together, so the failure message tells the whole story at once.
  it("reports added and stale together", () => {
    const found = [row("/ @1280", "button-name", 2)];
    expect(compareToBaseline(found, baseline)).toEqual({
      added: [["button-name@/ @1280", 2]],
      stale: [["target-size@/ @1280", 6]],
    });
  });
});

describe("the committed BASELINE", () => {
  // Proves: every baseline row belongs to a page label that some spec actually produces.
  // The comparison only looks at the rows whose label the running test passes in, so a row
  // whose label no test builds (a screen removed from the list, a width dropped, one side
  // of a label reworded) would never be compared, never go "stale", and sit in the file
  // looking like an enforced known problem: exactly the drift the "stale" half exists to
  // prevent. The labels come from `labels.ts`, the one place the specs build them.
  it("has no row that no spec exercises", () => {
    const orphans = BASELINE.filter((row) => !ALL_LABELS.has(row.page)).map((row) => row.page);

    expect(orphans).toEqual([]);
  });
});
