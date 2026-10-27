/**
 * The pinned clocks must agree with the sample data's window (B6-D2, C2-D2).
 *
 * The browser tests pin TWO clocks. The Next server's (`E2E_NOW`) decides the "Today" row, and
 * its date must fall inside the window the API serves, on a day that has shows; otherwise the
 * Today row is absent and every assertion about it is vacuous or wrong. The API's (`E2E_API_NOW`)
 * decides where that window starts, and must start it where `lib/fixtures` says it does.
 *
 * This is the build plan's "whenever the sample data changes, move the pinned date in the same
 * change" rule, as a red test instead of a memo.
 */
import { Temporal } from "@js-temporal/polyfill";
import { describe, expect, it } from "vitest";
import metro from "../../lib/fixtures/metro.json";
import shows from "../../lib/fixtures/shows.json";
import { E2E_API_NOW, E2E_NOW } from "./clock";

// Where the expected values come from: `lib/fixtures/shows.json` is generated from
// `apps/api/app/testing/sample_data.py` (`make fixtures`, kept current by `make
// contract-check`) and echoes the window the API serves in its `start` and `end`.
// That window, not the real calendar, is what the pins must agree with. The zone
// comes from `metro.json` too: "today" is the METRO's date, not the server's.
const metroDate = (instant: string): string =>
  Temporal.Instant.from(instant).toZonedDateTimeISO(metro.timezone).toPlainDate().toString();

describe("the pinned clock", () => {
  const pinnedDate = metroDate(E2E_NOW);

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

  // Proves (C2-D2): the API's pin starts the served window where the fixture says it starts. The API's default window
  // is "the metro's today plus 27 days", so the fixture's `start` is the API pin's local date. Moving the sample's START
  // without moving `E2E_API_NOW` (or the reverse) goes red here, instead of the browser specs finding a window that
  // doesn't match their expected counts.
  it("starts the served window where the fixture's window starts", () => {
    expect(metroDate(E2E_API_NOW)).toBe(shows.start);
  });
});
