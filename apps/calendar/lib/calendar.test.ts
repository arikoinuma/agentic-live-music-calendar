import { describe, expect, it } from "vitest";
import { groupCalendar, monthOptions } from "./calendar";
import months from "./fixtures/calendar-months.json";
import fixture from "./fixtures/shows.json";
import type { CalendarMonthsResponse, ShowListResponse, ShowSummary } from "./types";

// Where the expected values come from:
//  - Row counts are calendar arithmetic: 2026-09-28 to 2026-10-25
//    inclusive is 28 days (the API's default window is "start plus 27
//    days", routers/shows.py DEFAULT_WINDOW); October has 31 days; 2028 is
//    a leap year.
//  - The fixture rows are read off apps/api/app/sample_data.py's
//    _SHOW_ROWS: 2026-10-04 (offset 6) is "deliberately empty", and
//    2026-10-07 (offset 9) has The Terminal Bar at 21:00 plus the four
//    rows B3 added (White Squirrel 18:00 and 22:00, Zhora Darling 20:00,
//    Midway 01:00).
//  - Venue ids come from VENUES there: 1 White Squirrel, 2 Midway,
//    3 Zhora Darling, 4 Terminal Bar.

const served = fixture as ShowListResponse;

// A hand-built show: only the fields grouping reads matter.
const show = (
  id: number,
  date: string,
  venue: { id: number; name: string },
  start_time: string | null,
): ShowSummary => ({ id, date, start_time, venue, lineup: [] });

const squirrel = { id: 1, name: "The White Squirrel Bar" };
const midway = { id: 2, name: "The Midway Saloon" };
const zhora = { id: 3, name: "Zhora Darling" };

// --- the rows-------------------------------------------------------

describe("groupCalendar rows", () => {
  const group = (start: string, end: string, shows: ShowSummary[] = [], today: string | null = null) =>
    groupCalendar({ start, end, shows, today });

  it("has one row for every date in the served range, inclusive", () => {
    // Proves: rows come from the RANGE the server served, not from the
    // shows — that is how an empty day gets a row (plan D2), and the
    // inclusive end is the API's contract (api-contract.md §3). 28 days.
    const rows = group(served.start, served.end, served.shows);
    expect(rows).toHaveLength(28);
    expect(rows[0]?.date).toBe("2026-09-28");
    expect(rows[27]?.date).toBe("2026-10-25");
  });

  it("keeps a date with no shows as an empty row", () => {
    // Proves: the calendar renders a day with nothing on it (sample_data
    // keeps 2026-10-04 empty on purpose). A feed built from the shows
    // alone would skip it.
    const row = group(served.start, served.end, served.shows).find((r) => r.date === "2026-10-04");
    expect(row?.venues).toEqual([]);
  });

  it("makes one row for a one-day range", () => {
    // Proves: start == end is one row, not zero (the off-by-one the
    // exclusive-end mistake causes).
    expect(group("2026-10-07", "2026-10-07").map((r) => r.date)).toEqual(["2026-10-07"]);
  });

  it("walks through a leap day and a month end", () => {
    // Proves: date stepping is Temporal's: 2028 is a leap year, so
    // 2028-02-28 .. 2028-03-01 is three days including the 29th.
    expect(group("2028-02-28", "2028-03-01").map((r) => r.date)).toEqual([
      "2028-02-28",
      "2028-02-29",
      "2028-03-01",
    ]);
  });

  it("covers a whole calendar month", () => {
    // Proves: a `?month=2026-10` range (first to last day) yields 31 rows.
    expect(group("2026-10-01", "2026-10-31")).toHaveLength(31);
  });

  it("marks exactly the row that is today", () => {
    // Proves: the "Today" label lands on one row.
    const rows = group("2026-10-10", "2026-10-14", [], "2026-10-12");
    expect(rows.filter((r) => r.isToday).map((r) => r.date)).toEqual(["2026-10-12"]);
  });

  it("marks no row when today is outside the range, or unknown", () => {
    // Proves: a window that doesn't include today (a past month) shows no
    // "Today", and a null today (metro unavailable) can't match anything.
    expect(group("2026-10-10", "2026-10-14", [], "2026-11-01").some((r) => r.isToday)).toBe(false);
    expect(group("2026-10-10", "2026-10-14", [], null).some((r) => r.isToday)).toBe(false);
  });

  it("has every row empty when there are no shows", () => {
    // Proves: grouping doesn't decide the empty state; the page does.
    expect(group("2026-10-10", "2026-10-12").every((r) => r.venues.length === 0)).toBe(true);
  });

  it("ignores a show outside the served range", () => {
    // Proves: it neither invents a row nor throws. The API never sends
    // one; this pins that grouping doesn't depend on that.
    const rows = group("2026-10-10", "2026-10-11", [show(1, "2026-10-20", squirrel, "20:00:00")]);
    expect(rows.map((r) => r.date)).toEqual(["2026-10-10", "2026-10-11"]);
    expect(rows.every((r) => r.venues.length === 0)).toBe(true);
  });
});

// --- the columns -------------------------------------------------------------

describe("groupCalendar venue columns", () => {
  const day = "2026-10-09";
  const only = (shows: ShowSummary[]) =>
    groupCalendar({ start: day, end: day, shows, today: null })[0]?.venues ?? [];

  it("orders a day's venues alphabetically by name", () => {
    // Proves: plan D1 — columns are alphabetical, so a reader can find a
    // venue without hunting. "The Midway…" < "The White…" < "Zhora…".
    const columns = only([
      show(1, day, zhora, "20:00:00"),
      show(2, day, squirrel, "20:00:00"),
      show(3, day, midway, "20:00:00"),
    ]);
    expect(columns.map((c) => c.venue.name)).toEqual([
      "The Midway Saloon",
      "The White Squirrel Bar",
      "Zhora Darling",
    ]);
  });

  it("puts two shows at one venue in one column, in night order", () => {
    // Proves: a column holds every show at that venue that date (plan D7,
    // no cap), ordered by the night: 22:00, then 01:00 (after midnight,
    // later that night), then untimed. The input is deliberately shuffled.
    const columns = only([
      show(1, day, squirrel, null),
      show(2, day, squirrel, "01:00:00"),
      show(3, day, squirrel, "22:00:00"),
    ]);
    expect(columns).toHaveLength(1);
    expect(columns[0]?.shows.map((s) => s.id)).toEqual([3, 2, 1]);
  });

  it("keeps three or more shows at one venue", () => {
    // Proves: no cap at two (Ari, D7: the many-shows case is mostly an
    // all-day festival, and a cap would hide real shows).
    const columns = only([1, 2, 3, 4].map((id) => show(id, day, squirrel, `1${id}:00:00`)));
    expect(columns[0]?.shows).toHaveLength(4);
  });
});

describe("groupCalendar on the fixture", () => {
  // Computed inside each test (not at collection time), so an open gap
  // fails these tests one by one instead of failing the whole file.
  const oct7 = () =>
    groupCalendar({ start: served.start, end: served.end, shows: served.shows, today: null }).find(
      (r) => r.date === "2026-10-07",
    );

  it("gives 2026-10-07 all four venues", () => {
    // Proves: the layout's hardest row exists in the data (plan D5). Alphabetical
    // by name: Midway (2), Terminal (4), White Squirrel (1), Zhora (3).
    expect(oct7()?.venues.map((c) => c.venue.id)).toEqual([2, 4, 1, 3]);
  });

  it("holds White Squirrel's two shows early then late, and Midway's after-midnight show alone", () => {
    // Proves: 18:00 sorts before 22:00 in one column; Midway's 01:00 show
    // is still on the 7th's row (listed under that night).
    const columnFor = (id: number) => oct7()?.venues.find((c) => c.venue.id === id);
    expect(columnFor(1)?.shows.map((s) => s.start_time)).toEqual(["18:00:00", "22:00:00"]);
    expect(columnFor(2)?.shows.map((s) => s.start_time)).toEqual(["01:00:00"]);
  });
});

// --- the month dropdown ------------------------------------------------------

describe("monthOptions", () => {
  const offered = (months as CalendarMonthsResponse).months;

  it("labels the months the server offers", () => {
    // Proves: values are the URL form (`YYYY-MM`, zero-padded) and labels
    // the display form. The fixture offers September and October 2026.
    expect(monthOptions(offered, null)).toEqual([
      { value: "2026-09", label: "September 2026" },
      { value: "2026-10", label: "October 2026" },
    ]);
  });

  it("adds a current month the server didn't offer, in order", () => {
    // Proves: a hand-edited past month (allowed, plan B2 D2) still shows
    // in the select instead of the select claiming another month.
    expect(monthOptions(offered, "2026-02")).toEqual([
      { value: "2026-02", label: "February 2026" },
      { value: "2026-09", label: "September 2026" },
      { value: "2026-10", label: "October 2026" },
    ]);
  });

  it("does not duplicate a current month that is offered", () => {
    // Proves: selecting an offered month adds nothing.
    expect(monthOptions(offered, "2026-10")).toHaveLength(2);
  });
});
