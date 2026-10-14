import { describe, expect, it } from "vitest";
import { windowHref, windowLinks, windowNavLinks } from "./calendar-window";

// Where the expected values come from: calendar arithmetic worked out by
// hand, not read back from the code. The sample API's default window is
// 2026-09-28..2026-10-25 = 28 days inclusive (routers/shows.py:
// DEFAULT_WINDOW is "start plus 27 days"). 28 days before Sep 28 is Aug 31
// (Sep 28 - 27 = Sep 1, one more day = Aug 31); the day after Oct 25 is
// Oct 26. The paging links are computed from the range the SERVER echoed
// (api-contract.md §3), never from a clock or a constant 28.

// --- windowLinks (Gap B) ---------------------------------------------------------

describe("windowLinks", () => {
  it("steps back one window length and forward to the day after the end", () => {
    // Proves: the inclusive length (end - start + 1 = 28), not 27 — the
    // `+ 1` is the lesson. With 27, "earlier" would be 2026-09-01 and the
    // two windows would overlap by a day.
    expect(windowLinks("2026-09-28", "2026-10-25")).toEqual({
      earlier: "2026-08-31",
      later: "2026-10-26",
    });
  });

  it("handles a leap day", () => {
    // Proves: month arithmetic is Temporal's, not a hand-rolled 30-day
    // month. 2028 is a leap year: the day after Feb 28 is Feb 29, and 28
    // days before Feb 1 is Jan 4 (Jan has 31 days).
    expect(windowLinks("2028-02-01", "2028-02-28")).toEqual({
      earlier: "2028-01-04",
      later: "2028-02-29",
    });
  });

  it("crosses a year boundary", () => {
    // Proves: Dec 20 - Jan 16 is 12 + 16 = 28 days; 28 before Dec 20 is
    // Nov 22; the day after Jan 16 is Jan 17 of the next year.
    expect(windowLinks("2026-12-20", "2027-01-16")).toEqual({
      earlier: "2026-11-22",
      later: "2027-01-17",
    });
  });

  it("takes the window length from the range, not a constant", () => {
    // Proves: a one-day window pages by one day. If the length were a
    // hard-coded 28, a server that changed DEFAULT_WINDOW would make the
    // links lie; this is the "server owns the window" rule.
    expect(windowLinks("2026-10-07", "2026-10-07")).toEqual({
      earlier: "2026-10-06",
      later: "2026-10-08",
    });
  });
});

// --- windowHref -------------------------------------------------------------------

describe("windowHref", () => {
  it("appends ?from= for a date and nothing for null", () => {
    // Proves: `null` means "the server's default window" and produces the
    // bare path, so the default view has exactly one URL.
    expect(windowHref("/venue/3", "2026-10-26")).toBe("/venue/3?from=2026-10-26");
    expect(windowHref("/venue/3", null)).toBe("/venue/3");
  });
});

// --- windowNavLinks -----------------------------------------------------------------

describe("windowNavLinks", () => {
  it("builds both hrefs for an ordinary window", () => {
    // Proves: the pager's two links, as the page renders them.
    expect(windowNavLinks("/venue/3", "2026-09-28", "2026-10-25")).toEqual({
      earlier: "/venue/3?from=2026-08-31",
      later: "/venue/3?from=2026-10-26",
    });
  });

  it("drops only the link whose date parseFromParam would reject", () => {
    // Proves: a pager link that would silently land on the DEFAULT window
    // is not shown (plan review #5), and the other direction still works.
    // The parser is the one bound rule: years 1..9998 (the API's `start +
    // 27 days` overflows in 9999; year 0 is refused by the API). Worked
    // out by hand, both windows 28 days long:
    //  - 9998-12-20..9999-01-16: earlier 9998-11-22 is fine, later is
    //    9999-01-17 -> year 9999 -> dropped.
    //  - 0001-01-05..0001-02-01: later 0001-02-02 is fine, earlier is Dec 8
    //    of year 0 -> dropped.
    expect(windowNavLinks("/venue/3", "9998-12-20", "9999-01-16")).toEqual({
      earlier: "/venue/3?from=9998-11-22",
      later: null,
    });
    expect(windowNavLinks("/venue/3", "0001-01-05", "0001-02-01")).toEqual({
      earlier: null,
      later: "/venue/3?from=0001-02-02",
    });
  });
});
