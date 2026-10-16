import { describe, expect, it } from "vitest";
import {
  buildCalendarHref,
  parseCalendarFilters,
  parseDateParam,
  parseIdParam,
  parseMonthParam,
  toShowsQuery,
  type CalendarFilters,
  type SearchParams,
} from "./params";

// Every expected value in this file is written out by hand from the plan
// (docs/dev/implementations/b2-routes-and-data-loading.md, "Test approach
// §2") or from calendar arithmetic. None are read back from params.ts, so
// a wrong implementation can't agree with itself.

// Builds the object Next hands a page as `searchParams` from a query
// string: a key that appears once is a string, a repeated key is an array.
// Whether this matches what Next *really* passes is checked by the HTTP
// matrix in the plan's Verification step 4, not assumed here.
function searchParamsFrom(queryString: string): SearchParams {
  const out: SearchParams = {};
  for (const [key, value] of new URLSearchParams(queryString)) {
    const existing = out[key];
    if (existing === undefined) out[key] = value;
    else out[key] = [...(Array.isArray(existing) ? existing : [existing]), value];
  }
  return out;
}

const NO_FILTERS: CalendarFilters = { venueIds: [], artistIds: [], month: null };

// --- parseIdParam ----------------------------------------------------------

describe("parseIdParam", () => {
  it.each([
    ["12", 12],
    ["1", 1],
    ["2147483647", 2147483647], // the largest Postgres int4
  ])("accepts the positive integer %s", (raw, expected) => {
    // Proves: well-formed ids come through as numbers (the /venue/[id]
    // page passes this straight to the API client).
    expect(parseIdParam(raw)).toBe(expected);
  });

  it.each([
    "0",
    "-1",
    "1.5",
    "abc",
    "12abc",
    "",
    " 12",
    "1e3",
    "012", // leading zero: /venue/012 would be a second URL for /venue/12
    "2147483648", // int4 max + 1
    "99999999999999999999",
  ])("rejects %j", (raw) => {
    // Proves: anything that isn't a canonical positive int4 is null, so
    // the page can answer 404 instead of sending the API a value it
    // would 422 on, or that Postgres would reject as out of range once
    // the routers are DB-backed (B2-PR1-9).
    expect(parseIdParam(raw)).toBeNull();
  });
});

// --- parseDateParam --------------------------------------------------------

describe("parseDateParam", () => {
  it.each(["2026-10-08", "2024-02-29", "0001-01-01"])(
    "accepts %s",
    (raw) => {
      // Proves: real calendar dates parse, including a leap day and the
      // lowest year the API accepts.
      expect(parseDateParam(raw)?.toString()).toBe(raw);
    },
  );

  it.each([
    "2026-02-29", // 2026 is not a leap year
    "2026-02-30",
    "2026-13-01",
    "0000-01-01", // passes regex + Temporal, but the API 422s on year 0
    "2026-1-5", // not zero-padded
    "20261008", // ISO basic format: Temporal accepts it, we must not
    "2026-10-08T00:00", // date-time: Temporal accepts it, we must not
    "2026-10-08 ",
    "2026-10-08junk",
    "",
    "garbage",
  ])("rejects %j", (raw) => {
    // Proves: only strict YYYY-MM-DD for a real date is a page. Without
    // the regex guard, /day/20261008 and /day/2026-10-08T… would be extra
    // URLs for the same page; without the year >= 1 check a year-0 URL
    // would reach the API and come back as an error page, not a 404
    // (B2-PR1-8).
    expect(parseDateParam(raw)).toBeNull();
  });
});

// --- parseMonthParam -------------------------------------------------------

describe("parseMonthParam", () => {
  it.each([
    ["2026-10", "2026-10"],
    ["2028-02", "2028-02"],
    ["0001-01", "0001-01"],
  ])("accepts %s", (raw, expected) => {
    // Proves: well-formed `YYYY-MM` values (including leap February and the lowest year) come back
    // as the same string: it is the canonical URL form that buildCalendarHref writes back.
    expect(parseMonthParam(raw)).toBe(expected);
  });

  it.each(["2026-13", "2026-00", "26-10", "abc", "2026-1", "2026-10-01", "0000-10", ""])(
    "rejects %j",
    (raw) => {
      // Proves: a bad `month` is dropped (null), never thrown on, so a
      // stale bookmark still renders the default calendar.
      expect(parseMonthParam(raw)).toBeNull();
    },
  );

  it("treats a missing month as no month", () => {
    // Proves: an absent `month` key is "no month filter" (null), not an error, so the default window applies.
    expect(parseMonthParam(undefined)).toBeNull();
  });
});

// --- parseCalendarFilters (B2-K1) -------------------------------------------

describe("parseCalendarFilters", () => {
  it("returns no filters for an empty query", () => {
    // Proves: the default calendar is "no filters", not an error.
    expect(parseCalendarFilters({})).toEqual(NO_FILTERS);
  });

  it("reads a single value and a repeated key for venue and artist", () => {
    // Proves: Next's string-vs-array split is normalised. One `venue=1`
    // arrives as a string, `venue=1&venue=3` as a string[]; both must
    // produce a list (api-contract.md §2 uses repeated keys too).
    expect(parseCalendarFilters(searchParamsFrom("venue=1"))).toEqual({
      ...NO_FILTERS,
      venueIds: [1],
    });
    expect(
      parseCalendarFilters(searchParamsFrom("venue=1&venue=3&artist=7&artist=2")),
    ).toEqual({ ...NO_FILTERS, venueIds: [1, 3], artistIds: [2, 7] });
  });

  it("drops invalid entries one by one and never throws", () => {
    // Proves: the URL is user input. `venue=1&venue=abc&venue=-2` keeps
    // the 1; a hand-edited or stale bookmark must not 500 the page.
    expect(
      parseCalendarFilters(searchParamsFrom("venue=1&venue=abc&venue=-2")),
    ).toEqual({ ...NO_FILTERS, venueIds: [1] });
    expect(parseCalendarFilters(searchParamsFrom("venue=abc"))).toEqual(NO_FILTERS);
  });

  it("collapses duplicates and sorts numerically", () => {
    // Proves: one filter set has one canonical form (so one URL).
    // `venue=10&venue=9` must be [9, 10]; the default Array sort is
    // lexicographic and would give [10, 9].
    expect(
      parseCalendarFilters(searchParamsFrom("venue=10&venue=9&venue=10")),
    ).toEqual({ ...NO_FILTERS, venueIds: [9, 10] });
  });

  it("reads month, using the first value when it repeats, and ignores unrelated keys", () => {
    // Proves: `month` parses through parseCalendarFilters, a repeated key uses the first VALID value, and
    // unrelated keys (`utm=x`) never leak into the filters. Expected values are written by hand.
    expect(parseCalendarFilters(searchParamsFrom("month=2026-10&utm=x"))).toEqual({
      ...NO_FILTERS,
      month: "2026-10",
    });
    expect(
      parseCalendarFilters(searchParamsFrom("month=2026-10&month=2026-11")),
    ).toEqual({ ...NO_FILTERS, month: "2026-10" });
    // "first valid value": a bad first entry does not hide a good second one.
    expect(
      parseCalendarFilters(searchParamsFrom("month=abc&month=2026-11")),
    ).toEqual({ ...NO_FILTERS, month: "2026-11" });
  });
});

// --- toShowsQuery (B2-K2) ---------------------------------------------------

describe("toShowsQuery", () => {
  it("sends no start/end without a month, so the server picks its default window", () => {
    // Proves: the client never invents a date range ("the server owns now",
    // api-contract.md §3).
    const query = toShowsQuery({ venueIds: [1], artistIds: [], month: null });
    expect(query).toEqual({ venueIds: [1], artistIds: [] });
    expect("start" in query).toBe(false);
    expect("end" in query).toBe(false);
  });

  // Expected bounds are calendar facts, not computed by the code under test.
  it.each([
    ["2026-10", "2026-10-01", "2026-10-31"], // 31 days
    ["2026-09", "2026-09-01", "2026-09-30"], // 30 days
    ["2026-02", "2026-02-01", "2026-02-28"], // common-year February
    ["2028-02", "2028-02-01", "2028-02-29"], // leap-year February
    ["2026-12", "2026-12-01", "2026-12-31"], // year boundary: not 2027-01-01
  ])("month %s covers %s through %s inclusive", (month, start, end) => {
    // Proves: `month` means the whole calendar month literally (decision
    // B2-D2). The API's `end` is inclusive, so end is the LAST day of the
    // month — the likeliest bug is the first of the next month.
    const query = toShowsQuery({ ...NO_FILTERS, month });
    expect(query.start).toBe(start);
    expect(query.end).toBe(end);
  });

  it("carries the venue and artist ids through unchanged", () => {
    // Proves: toShowsQuery changes nothing but the month, which becomes the whole-month start/end;
    // the ids pass through in their canonical order.
    expect(
      toShowsQuery({ venueIds: [1, 3], artistIds: [7], month: "2026-10" }),
    ).toEqual({
      start: "2026-10-01",
      end: "2026-10-31",
      venueIds: [1, 3],
      artistIds: [7],
    });
  });
});

// --- buildCalendarHref -------------------------------------------------------

describe("buildCalendarHref", () => {
  it("is just '/' with no filters", () => {
    // Proves: the unfiltered calendar's canonical URL is plain "/", not "/?".
    expect(buildCalendarHref(NO_FILTERS)).toBe("/");
  });

  it("writes keys in a fixed order: venue, artist, month", () => {
    // Proves: the href is canonical regardless of how the object was
    // built, which keeps filtered URLs shareable and cache-friendly.
    expect(
      buildCalendarHref({ month: "2026-10", artistIds: [7], venueIds: [1, 3] }),
    ).toBe("/?venue=1&venue=3&artist=7&month=2026-10");
  });

  it("round-trips: parsing what it built gives back the same filters", () => {
    // Proves: (together with the next test) that filters are shareable and
    // bookmarkable: URL -> filters -> URL is stable. Clean input here.
    const filters: CalendarFilters = {
      venueIds: [1, 3],
      artistIds: [7],
      month: "2026-10",
    };
    const href = buildCalendarHref(filters);
    const queryString = href.slice(href.indexOf("?") + 1);
    expect(parseCalendarFilters(searchParamsFrom(queryString))).toEqual(filters);
  });

  it("canonicalises messy input into the one canonical href", () => {
    // Proves: unsorted, duplicated and partly invalid input all collapse
    // to a single URL (B2-PR1-13).
    const messy = searchParamsFrom("venue=3&venue=1&venue=3&venue=x");
    expect(buildCalendarHref(parseCalendarFilters(messy))).toBe(
      "/?venue=1&venue=3",
    );
  });
});
