/**
 * The pinned clock must sit inside the sample data's window (B6 plan, D2).
 *
 * The browser tests pin the Next server's clock to ONE instant (`E2E_NOW`) so the
 * "Today" row is deterministic. That instant is only useful if its date falls
 * inside the window the API serves and on a day that has shows; otherwise the
 * Today row is absent and every assertion about it is vacuous or wrong.
 *
 * This is the build plan's "whenever sample_data.py changes, move the pinned date
 * in the same change" rule, as a red test instead of a memo.
 */
import { Temporal } from "@js-temporal/polyfill";
import { describe, expect, it } from "vitest";
import metro from "../../lib/fixtures/metro.json";
import shows from "../../lib/fixtures/shows.json";
import { E2E_NOW } from "./clock";

// Where the expected values come from: `lib/fixtures/shows.json` is generated from
// `apps/api/app/sample_data.py` (`make fixtures`, kept current by `make
// contract-check`) and echoes the window the API serves in its `start` and `end`.
// That window, not the real calendar, is what the pin must land inside. The zone
// comes from `metro.json` too: "today" is the METRO's date, not the server's.
describe("the pinned clock", () => {
  const pinnedDate = Temporal.Instant.from(E2E_NOW)
    .toZonedDateTimeISO(metro.timezone)
    .toPlainDate()
    .toString();

  // Proves: the pin lands in the served window. A new `START` in sample_data.py
  // moves the window; this goes red in `pnpm test` the same day, so the pin moves
  // in the same change instead of being found when the Today assertions fail.
  it("falls on a date inside the window the API serves", () => {
    expect(pinnedDate >= shows.start).toBe(true);
    expect(pinnedDate <= shows.end).toBe(true);
  });

  // Proves: the pinned date has at least one show, so the Today row is a populated
  // row and the "Wed, Oct 7 holds five shows" assertion in home.spec.ts can mean
  // something. An in-window but empty day would pass the first test and leave the
  // browser test checking an empty row.
  it("falls on a day that has shows", () => {
    expect(shows.shows.some((s) => s.date === pinnedDate)).toBe(true);
  });
});
