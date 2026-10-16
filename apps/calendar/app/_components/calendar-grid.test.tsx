import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { CalendarRow, VenueColumn } from "@/lib/calendar";
import type { ShowSummary, VenueSummary } from "@/lib/types";
import { CalendarGrid } from "./calendar-grid";

// What this file tests (B5, section 2 of the plan): what CalendarGrid DOES
// WITH the rows it is handed — one list item per date, the "Today" marker,
// the thin "Nothing listed" row, and a column per venue holding its shows.
// It does not test how shows become rows: that is `groupCalendar`, which
// has its own pure tests (lib/calendar.test.ts) and runs end to end in
// calendar-results.test.tsx.
//
// The rows below are built BY HAND on purpose, independent of
// `groupCalendar`. If this file fed the grid with `groupCalendar`'s output,
// a bug in one could hide a bug in the other.
//
// Where the expected values come from:
//  - Weekdays are calendar facts: 2026-10-07 is a Wednesday (B4's fixture
//    day), so the 6th is a Tuesday and the 8th a Thursday. The heading
//    format ("Wed, Oct 7") is the one lib/dates.test.ts pins.
//  - Everything else is read off the rows each test builds.

// --- hand-built rows --------------------------------------------------------

const squirrel: VenueSummary = { id: 1, name: "The White Squirrel Bar" };
const zhora: VenueSummary = { id: 3, name: "Zhora Darling" };

// A show with only the fields the grid and the show block read. An empty
// lineup is fine: this file is about the grid, not about lineups.
const show = (id: number, venue: VenueSummary, date = "2026-10-07"): ShowSummary => ({
  id,
  date,
  start_time: "20:00:00",
  venue,
  lineup: [],
});

const column = (venue: VenueSummary, shows: ShowSummary[]): VenueColumn => ({ venue, shows });

const row = (date: string, venues: VenueColumn[] = [], isToday = false): CalendarRow => ({
  date,
  isToday,
  venues,
});

// The grid's rows are the direct children of its <ol>. A show block's
// lineup is a <ul> with its own <li>s, so "every listitem" would count
// those too; this keeps to one list item per DATE.
function dateRows(): HTMLElement[] {
  return screen.getAllByRole("listitem").filter((li) => li.parentElement?.tagName === "OL");
}

// --- the rows ---------------------------------------------------------------

describe("CalendarGrid rows", () => {
  it("renders one list item per row, in the order given, each headed by a link to its day", () => {
    // Proves: every date handed to the grid gets a row — including a date
    // with nothing on it, which is how an empty day stays visible (B3-D2) —
    // and each heading is the link to that day's page (/day/<date>), in the
    // short "Wed, Oct 7" form. The grid must not drop or reorder rows.
    render(
      <CalendarGrid rows={[row("2026-10-06"), row("2026-10-07"), row("2026-10-08")]} />,
    );

    expect(dateRows()).toHaveLength(3);
    const headings = screen.getAllByRole("heading", { level: 2 });
    expect(headings.map((h) => h.textContent)).toEqual(["Tue, Oct 6", "Wed, Oct 7", "Thu, Oct 8"]);
    expect(screen.getByRole("link", { name: "Wed, Oct 7" })).toHaveAttribute(
      "href",
      "/day/2026-10-07",
    );
  });

  it("marks the row that is today, and only that row", () => {
    // Proves: `isToday` becomes the accessible state `aria-current="date"`
    // plus a visible "Today" badge, on exactly one row. Asserted through
    // the role query's `current` option rather than a class, because the
    // attribute is what a screen reader announces. A grid that dropped the
    // attribute (mutation B5-M6) would look the same and tell nobody.
    render(
      <CalendarGrid rows={[row("2026-10-06"), row("2026-10-07", [], true), row("2026-10-08")]} />,
    );

    const current = screen.getAllByRole("listitem", { current: "date" });
    expect(current).toHaveLength(1);
    expect(within(current[0]!).getByRole("link", { name: /Wed, Oct 7/ })).toBeInTheDocument();
    expect(within(current[0]!).getByText("Today")).toBeInTheDocument();
    expect(screen.getAllByText("Today")).toHaveLength(1);
  });

  it("marks no row when none is today", () => {
    // Proves: `today` can be unknown (no metro, or a window that doesn't
    // reach today), and then nothing is highlighted — better than guessing.
    render(<CalendarGrid rows={[row("2026-10-06"), row("2026-10-07")]} />);

    expect(screen.queryByRole("listitem", { current: "date" })).not.toBeInTheDocument();
    expect(screen.queryByText("Today")).not.toBeInTheDocument();
  });

  it("shows a thin 'Nothing listed' line, and no venue headings, for a row with no venues", () => {
    // Proves: an empty date is a quiet line, not a blank gap and not an
    // empty column (B3-D2).
    render(<CalendarGrid rows={[row("2026-10-07")]} />);

    expect(screen.getByText("Nothing listed")).toBeInTheDocument();
    expect(screen.queryAllByRole("heading", { level: 3 })).toHaveLength(0);
  });
});

// --- the venue columns ------------------------------------------------------

describe("CalendarGrid venue columns", () => {
  it("renders a column per venue, in the order given, each headed by a link to the venue", () => {
    // Proves: the column header is the link to /venue/<id>, and the grid
    // keeps the order it was handed. Alphabetising is groupCalendar's job
    // (B3-D1); a grid that re-sorted would hide a grouping bug.
    render(
      <CalendarGrid
        rows={[
          row("2026-10-07", [
            column(zhora, [show(24, zhora)]),
            column(squirrel, [show(22, squirrel)]),
          ]),
        ]}
      />,
    );

    const venueHeadings = screen.getAllByRole("heading", { level: 3 });
    expect(venueHeadings.map((h) => h.textContent)).toEqual(["Zhora Darling", "The White Squirrel Bar"]);
    expect(within(venueHeadings[0]!).getByRole("link")).toHaveAttribute("href", "/venue/3");
    expect(within(venueHeadings[1]!).getByRole("link")).toHaveAttribute("href", "/venue/1");
  });

  it("keeps each show in its own venue's column", () => {
    // Proves: shows sit under the venue they belong to. Two venues with a
    // different number of shows each, so a column that picked up another
    // venue's blocks changes a count.
    render(
      <CalendarGrid
        rows={[
          row("2026-10-07", [
            column(squirrel, [show(22, squirrel), show(23, squirrel)]),
            column(zhora, [show(24, zhora)]),
          ]),
        ]}
      />,
    );

    const columns = screen.getAllByRole("heading", { level: 3 }).map((h) => h.closest("section")!);
    expect(within(columns[0]!).getAllByRole("article")).toHaveLength(2);
    expect(within(columns[1]!).getAllByRole("article")).toHaveLength(1);
  });

  it("renders every show at a venue, with no cap at two", () => {
    // Proves: B3-D7. "1-2 shows" in the requirements describes the usual
    // case, and a cap would hide a real third show.
    const shows = [show(1, squirrel), show(2, squirrel), show(3, squirrel)];
    render(<CalendarGrid rows={[row("2026-10-07", [column(squirrel, shows)])]} />);

    expect(screen.getAllByRole("article")).toHaveLength(3);
  });
});
