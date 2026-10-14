/**
 * The calendar's shape: the API's flat list of shows -> date rows, each
 * holding one column per venue that has a show that day.
 *
 * Plan D1 (docs/dev/implementations/b3-the-calendar.md): a row lists only
 * the venues with a show that date, alphabetically — not every venue on
 * every date. A real metro has tens of venues and most are dark on most
 * nights, so an aligned grid would be mostly empty cells; this is the
 * "closer to a feed than a grid" shape arch-initial.md §4 describes. The
 * price is that a venue isn't in the same horizontal position on every
 * date; "what is on at venue X" is the venue filter's job and the venue
 * page's (B4), not this layout's.
 *
 * Pure and Temporal-based (dates stay ISO strings in the output; Temporal
 * is used to count days). Server-side only, like lib/dates.ts.
 */

import { Temporal } from "@js-temporal/polyfill";
import { formatMonthLabel, nightSortKey } from "./dates";
import type { CalendarMonth, ShowSummary, VenueSummary } from "./types";

export type VenueColumn = { venue: VenueSummary; shows: ShowSummary[] };

// One date's row. `venues` is empty for a date with no shows — the row
// still exists (plan D2), and the page renders it as a thin "Nothing
// listed" line.
export type CalendarRow = {
  date: string;
  isToday: boolean;
  venues: VenueColumn[];
};

/**
 * Groups `shows` into one row per date from `start` to `end` inclusive.
 *
 * `start` and `end` are the range the SERVER says it served
 * (`ShowListResponse.start/end`, api-contract.md §3 "the server owns
 * now"); `today` is the metro's current date as an ISO string, or null
 * when it couldn't be determined (then no row is marked).
 *
 * Does not sort by the API's order: a day's shows are re-sorted by
 * `nightSortKey`, because the API sorts by clock time, which puts a
 * 1:00 AM show FIRST in its day (a follow-up for A1b, recorded in the B3
 * plan) — and this layout must not depend on that.
 */
export function groupCalendar(input: {
  start: string;
  end: string;
  shows: ShowSummary[];
  today: string | null;
}): CalendarRow[] {
  const { start, end, shows, today } = input;

  const emptyRow = (date: Temporal.PlainDate): CalendarRow => ({
    date: date.toString(),
    isToday: date.toString() === today,
    venues: [],
  });

  // (Ari) — Gap C. Lesson: the calendar's rows come from the RANGE the
  //   server served, NOT from the shows — that is how an empty day gets a
  //   row (plan D2), and why the page renders `start`/`end` from the
  //   response (api-contract.md §3). Walk it with Temporal: `add({ days:
  //   1 })` handles month ends and leap days, `compare` handles the
  //   INCLUSIVE end (Temporal objects throw on `<=`).
  // Code (replace the `todo` line, and delete `import { todo } from "./todo"` —
  //   nothing else in this file calls it):
  //   const rows: CalendarRow[] = [];
  //   for (let d = Temporal.PlainDate.from(start);
  //        Temporal.PlainDate.compare(d, end) <= 0;
  //        d = d.add({ days: 1 })) {
  //     rows.push(emptyRow(d));
  //   }
  // Check: `pnpm --filter calendar test calendar` — the 28-row fixture
  //   case, the one-day range and the leap-year range. Likeliest
  //   mistakes: `< 0` (drops the last day; the API's `end` is inclusive),
  //   `d <= end` (throws), or building rows from `shows.map(s => s.date)`
  //   (passes the venue tests, fails the empty-day one).
  const rows: CalendarRow[] = [];
  for (let d = Temporal.PlainDate.from(start);
        Temporal.PlainDate.compare(d, end) <= 0;
        d = d.add({ days: 1 })) {
    rows.push(emptyRow(d));
  }

  // Bucket the shows into the rows by date. A show outside the range has
  // no row and is ignored (the API never sends one).
  const rowByDate = new Map(rows.map((row) => [row.date, row]));
  for (const show of shows) {
    const row = rowByDate.get(show.date);
    if (row === undefined) continue;
    let column = row.venues.find((c) => c.venue.id === show.venue.id);
    if (column === undefined) {
      column = { venue: show.venue, shows: [] };
      row.venues.push(column);
    }
    column.shows.push(show);
  }

  // Columns alphabetical by venue name (plan D1); within a column, shows
  // in the order they happen that night.
  for (const row of rows) {
    row.venues.sort((a, b) => a.venue.name.localeCompare(b.venue.name, "en-US"));
    for (const column of row.venues) {
      column.shows.sort((a, b) => nightSortKey(a.start_time) - nightSortKey(b.start_time));
    }
  }
  return rows;
}

/**
 * The month dropdown's options: `{ value: "2026-10", label: "October 2026" }`.
 *
 * `months` is what `GET /calendar/months` returned — future-facing months
 * that have shows; the server decides both (api-contract.md §2). If the
 * URL's current month isn't among them (a hand-edited past month is
 * allowed, B2 decision D2), it is added so the select can show what the
 * calendar is actually showing instead of claiming another month.
 */
export function monthOptions(
  months: CalendarMonth[],
  current: string | null,
): { value: string; label: string }[] {
  const pad = (n: number) => String(n).padStart(2, "0");
  const options = months.map((m) => ({
    value: `${m.year}-${pad(m.month)}`,
    label: formatMonthLabel(m.year, m.month),
  }));
  if (current !== null && !options.some((o) => o.value === current)) {
    // `current` came through parseMonthParam, so it is a valid YYYY-MM.
    options.push({
      value: current,
      label: formatMonthLabel(Number(current.slice(0, 4)), Number(current.slice(5, 7))),
    });
    options.sort((a, b) => a.value.localeCompare(b.value));
  }
  return options;
}
